"""One immutable-in-use upgrade plan shared by preview and execution."""

from concurrent.futures import ThreadPoolExecutor

from . import InfraError
from .catalog import CLIENT, SERVICES
from .registry import numbers


def image_repository(service) -> str:
    return service.repository.removeprefix("library/")


def matches(image: dict | None, metadata: dict) -> bool:
    local = {value.split("@", 1)[-1] for value in (image or {}).get("RepoDigests", [])}
    remote = {
        metadata["digest"],
        *(value["digest"] for value in metadata.get("images", []) if value.get("digest")),
    }
    return bool(local & remote)


def plan(docker, registry, targets: list[str], *, to: str | None, backup: bool) -> dict:
    if to and len(targets) != 1:
        raise InfraError("one_target")
    config = docker.config()
    containers = docker.service_containers()
    data_issues = docker.data_issues(targets, containers)
    selected = [SERVICES[name] for name in targets]
    if "s3" in targets:
        selected.append(CLIENT)

    def inspect(service):
        configured = docker.instance.values[service.version_key]
        source = config["services"][service.name]["image"]
        container = containers.get(service.name)
        runtime_image = (container or {}).get("Config", {}).get("Image", source)
        runtime_tag = runtime_image.split("@", 1)[0].rsplit(":", 1)[-1]
        reference = container["Image"] if container else source
        current = docker.image(reference)
        try:
            latest = registry.latest(service, configured)
            metadata = latest
            if to and service.name in targets:
                parts = len(numbers(to))
                if parts <= service.scope_parts:
                    metadata = registry.latest(service, to)
                elif parts == service.release_parts:
                    metadata = registry.exact(service.repository, to)
                else:
                    raise InfraError(f"invalid_version|{to}")
            target_version = metadata["name"]
            # Alias targets such as --to 18 resolve to a concrete stable release.
            if len(numbers(target_version)) <= service.scope_parts:
                metadata = registry.latest(service, target_version)
                target_version = metadata["name"]
            source_version = (
                latest["name"] if matches(current, latest) else configured.split("@", 1)[0]
            )
            reason = data_issues.get(service.name)
            if service.scope(runtime_tag) != service.scope(target_version) or service.scope(
                configured
            ) != service.scope(target_version):
                reason = "migration_required"
            elif (
                to
                and numbers(target_version) < numbers(source_version)
                or to
                and len(numbers(source_version)) < 3
                and not matches(current, latest)
                and numbers(target_version) < numbers(latest["name"])
            ):
                reason = "downgrade_blocked"
            state = (
                "current"
                if matches(current, metadata)
                else "update_available"
                if current
                else "not_downloaded"
            )
            ready = bool(
                container
                and container["State"].get("Status") == "running"
                and container["State"].get("Health", {}).get("Status", "healthy") == "healthy"
            )
            return {
                "service": service.name,
                "state": "blocked" if reason else state,
                "image": source,
                "runtime_image": runtime_image,
                "target": f"{image_repository(service)}:{target_version}@{metadata['digest']}",
                "version": f"{target_version}@{metadata['digest']}",
                "version_key": service.version_key,
                "change": not ready or state != "current"
                if service.name != "s3-client"
                else state != "current",
                "reason": reason,
            }
        except (OSError, ValueError, KeyError) as exc:
            return {
                "service": service.name,
                "state": "error",
                "image": source,
                "target": "",
                "change": False,
                "error": str(exc),
            }

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(executor.map(inspect, selected))
    return {
        "complete": all(r["state"] != "error" for r in records),
        "blocked": any(r.get("reason") for r in records),
        "backup": backup,
        "services_selected": targets,
        "images": records,
        "instance_signature": docker.instance.signature(),
        "steps": [
            "validate",
            "backup" if backup else "skip_backup",
            "pull",
            "save_versions",
            "recreate",
            "healthcheck",
        ],
        "migration_guide": str(docker.instance.root / "docs/upgrades.md"),
    }
