"""Service operations consume validated selections and shared plans."""

import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

from . import ROOT, InfraError, __version__, data, planning
from .catalog import SERVICES


def overview(docker, targets: list[str]) -> dict:
    available = docker.available()
    config = docker.config() if available else None
    containers = docker.service_containers() if available else {}
    records = []
    for name in targets:
        service = SERVICES[name]
        container = containers.get(name)
        state = "unavailable" if not available else "not_created"
        image = (
            config["services"][name]["image"]
            if config
            else f"{planning.image_repository(service)}:{docker.instance.values[service.version_key]}"
        )
        if container:
            runtime = container["State"]
            state = (
                runtime.get("Health", {}).get("Status", runtime["Status"])
                if runtime["Status"] == "running"
                else runtime["Status"]
            )
            image = container["Config"]["Image"]
        host = docker.instance.values["KAFKA_ADVERTISED_HOST" if name == "kafka" else "BIND_HOST"]
        records.append(
            {
                "service": name,
                "state": state,
                "image": image,
                "endpoint": f"{host}:{docker.instance.values[service.port_key]}",
                "volume": docker.instance.values[service.volume_key],
            }
        )
    return {"complete": available, "services": records}


def details(docker, targets: list[str], *, secrets: bool, open_page: bool) -> dict:
    result = overview(docker, targets)
    values = docker.instance.values
    for record in result["services"]:
        name = record["service"]
        host = values["BIND_HOST"]
        password = lambda key: values[key] if secrets else "***"
        if name in ("mysql", "postgres"):
            prefix = "MYSQL" if name == "mysql" else "POSTGRES"
            database = values["MYSQL_DATABASE" if name == "mysql" else "POSTGRES_DB"]
            record["connection"] = (
                f"{'mysql' if name == 'mysql' else 'postgresql'}://{quote(values[prefix + '_USER'], safe='')}:{quote(password(prefix + '_PASSWORD'), safe='')}@{host}:{values[prefix + '_PORT']}/{quote(database, safe='')}"
            )
            if name == "mysql":
                record["root_password"] = password("MYSQL_ROOT_PASSWORD")
        elif name == "redis":
            record["connection"] = f"redis://{host}:{values['REDIS_PORT']}"
        elif name == "kafka":
            record["connection"] = record["endpoint"]
        elif name == "s3":
            record.update(
                connection=f"http://{host}:{values['S3_PORT']}",
                web=f"http://{host}:{values['S3_ADMIN_PORT']}/rustfs/console/index.html",
                access_key=values["S3_ACCESS_KEY"],
                secret_key=password("S3_SECRET_KEY"),
                bucket=values["S3_BUCKET"],
                region=values["S3_REGION"],
            )
        else:
            record.update(
                connection=f"smtp://{host}:{values['MAILPIT_SMTP_PORT']}",
                web=f"http://{host}:{values['MAILPIT_UI_PORT']}",
            )
        if open_page:
            if not record.get("web"):
                raise InfraError("web_unavailable")
            if os.name == "nt":
                webbrowser.open(record["web"])
            else:
                subprocess.run(["explorer.exe", record["web"]], check=False)
    return result


def check(docker) -> dict:
    records = []
    available = docker.available()
    records.append({"check": "docker", "state": "ok" if available else "error"})
    if available:
        try:
            docker.config()
            records.append({"check": "compose", "state": "ok"})
        except (InfraError, OSError) as exc:
            records.append({"check": "compose", "state": "error", "detail": str(exc)})
    mysql = docker.instance.root / "config/mysql/my.cnf"
    records.append(
        {
            "check": "mysql_config_permissions",
            "state": "skipped"
            if os.name == "nt"
            else "error"
            if mysql.stat().st_mode & 0o002
            else "ok",
        }
    )
    records.append({"check": "port_declarations", "state": "ok"})
    return {"complete": all(r["state"] != "error" for r in records), "checks": records}


def lifecycle(docker, settings, action: str, targets: list[str]) -> dict:
    docker.require()
    docker.config()
    with docker.instance.lock():
        if action in ("start", "restart"):
            docker.validate_data(targets)
        docker.instance.initialize()
        if action in ("start", "restart"):
            docker.ensure_volumes(targets)
            docker.up(targets, settings.wait_timeout, recreate=action == "restart")
        elif action == "stop":
            docker.compose("stop", *targets, timeout=settings.wait_timeout + 30)
        else:
            removed = [*targets, *(["s3-permissions"] if "s3" in targets else [])]
            docker.compose("rm", "-f", "-s", *removed, timeout=settings.wait_timeout + 30)
    return overview(docker, targets)


def upgrade(docker, settings, proposal: dict) -> dict:
    if not proposal["complete"]:
        raise InfraError("query_failed")
    if proposal["blocked"]:
        reason = next(record["reason"] for record in proposal["images"] if record.get("reason"))
        raise InfraError(reason)
    changes = [record for record in proposal["images"] if record["change"]]
    if not changes:
        return {**proposal, "state": "unchanged"}
    with docker.instance.lock():
        # Regenerate local validation while preserving the reviewed remote targets.
        if docker.instance.signature() != proposal["instance_signature"]:
            raise InfraError("plan_changed")
        docker.config()
        docker.validate_data(proposal["services_selected"])
        docker.instance.initialize()
        journal = {**proposal, "state": "running", "completed_steps": []}
        docker.instance.save_state("last-upgrade.json", journal)
        try:
            if proposal["backup"]:
                databases = [r["service"] for r in changes if r["service"] in ("mysql", "postgres")]
                backups = data.backup(docker, databases)
                if any(record["state"] != "complete" for record in backups):
                    raise InfraError("backup_unavailable")
            journal["completed_steps"].append("backup" if proposal["backup"] else "skip_backup")
            # Pull everything before altering declarations or restarting any service.
            for record in changes:
                docker.run("pull", record["target"], timeout=600)
            journal["completed_steps"].append("pull")
            docker.instance.save_versions({r["version_key"]: r["version"] for r in changes})
            journal["completed_steps"].append("save_versions")
            docker.instance.save_state("last-upgrade.json", journal)
            targets = [r["service"] for r in changes if r["service"] in SERVICES]
            if not targets and any(r["service"] == "s3-client" for r in changes):
                targets = ["s3"]
            docker.ensure_volumes(targets)
            docker.up(targets, settings.wait_timeout)
            journal["completed_steps"].extend(["recreate", "healthcheck"])
            journal["state"] = "complete"
        except BaseException:
            journal["state"] = "error"
            docker.instance.save_state("last-upgrade.json", journal)
            raise
        docker.instance.save_state("last-upgrade.json", journal)
        return journal


def reset(docker, settings, targets: list[str], *, dry_run: bool, yes: bool) -> dict:
    if len(targets) != 1:
        raise InfraError("one_target")
    name = targets[0]
    volume = docker.instance.values[SERVICES[name].volume_key]
    containers = docker.service_containers()
    own = {
        c["Name"].lstrip("/")
        for key, c in containers.items()
        if key == name or name == "s3" and key == "s3-permissions"
    }
    users = docker.volume_users(volume)
    if set(users) - own:
        raise InfraError(f"volume_busy|{volume}")
    proposal = {
        "action": "reset",
        "service": name,
        "volume": volume,
        "users": users,
        "steps": ["stop", "remove_container", "delete_volume", "create_volume", "start"],
    }
    if dry_run:
        return proposal
    if not yes:
        raise InfraError("confirm_required")
    with docker.instance.lock():
        docker.config()
        image_names = [name, *(["s3-client"] if name == "s3" else [])]
        config = docker.config()
        if any(docker.image(config["services"][key]["image"]) is None for key in image_names):
            docker.compose("pull", *image_names, timeout=600)
        docker.instance.initialize()
        selected = [name, *(["s3-permissions"] if name == "s3" else [])]
        docker.compose("stop", *selected)
        docker.compose("rm", "-f", *selected)
        if docker.volume_users(volume):
            raise InfraError(f"volume_busy|{volume}")
        if docker.run("volume", "inspect", volume, check=False).returncode == 0:
            docker.run("volume", "rm", volume)
        docker.ensure_volumes(targets)
        docker.up(targets, settings.wait_timeout)
    return {**proposal, "state": "complete"}


def verify_source(source: Path) -> None:
    result = subprocess.run(
        ["git", "-C", str(source), "remote", "get-url", "origin"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode or not re.fullmatch(
        r"(?:git@github\.com:|https://github\.com/)hhhxxxddd/dev-infra(?:\.git)?",
        result.stdout.strip(),
    ):
        raise InfraError("unverified_source")
    if not (source / "scripts/install.sh").is_file():
        raise InfraError("unverified_source")


def self_command(action: str, source: str | None, settings) -> dict:
    if action == "status":
        return {
            "controller_version": __version__,
            "python_version": sys.version.split()[0],
            "python_executable": str(Path(sys.executable).resolve()),
            "root": str(ROOT),
            "source": (ROOT / ".source").read_text(encoding="utf-8").strip()
            if (ROOT / ".source").exists()
            else str(ROOT),
            "distro": settings.distro,
        }
    checkout = (
        Path(source)
        if source
        else Path((ROOT / ".source").read_text(encoding="utf-8").strip())
        if (ROOT / ".source").exists()
        else ROOT
    )
    if not checkout.exists():
        raise InfraError("source_missing")
    checkout = checkout.resolve()
    verify_source(checkout)
    if os.name == "nt":
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            str(checkout / "scripts/install.ps1"),
            "-Distro",
            settings.distro,
        ]
    else:
        if os.geteuid() != 0:
            raise InfraError("root_required")
        command = ["bash", str(checkout / "scripts/install.sh")]
    result = subprocess.run(command, check=False, stdout=sys.stderr, stderr=sys.stderr)
    if result.returncode:
        raise InfraError(f"install_failed|{result.returncode}")
    return {"state": "complete", "source": str(checkout)}
