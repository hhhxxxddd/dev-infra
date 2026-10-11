"""Service operations consume validated selections and shared plans."""

import os
import re
import subprocess
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, quote_plus

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


def _upgrade_time() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _upgrade_error(exc: BaseException, instance) -> dict:
    """Keep useful diagnostics without recording command argv, SQL or credentials."""
    code = str(exc).partition("|")[0] if isinstance(exc, InfraError) else "operation_failed"
    if not re.fullmatch(r"[a-z_]+", code):
        code = "operation_failed"
    if isinstance(exc, subprocess.TimeoutExpired):
        code, detail = "operation_timeout", f"timeout={exc.timeout}"
    elif isinstance(exc, subprocess.CalledProcessError):
        code, detail = "command_failed", f"exit={exc.returncode}"
    elif isinstance(exc, (KeyboardInterrupt, SystemExit)):
        code, detail = "operation_interrupted", ""
    else:
        detail = str(exc)
        if re.search(
            r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|SELECT\s+|"
            r"COPY\s+.+?\s+FROM|(?:CREATE|ALTER|DROP)\s+(?:USER|ROLE|TABLE|DATABASE)|"
            r"IDENTIFIED\s+BY)",
            detail,
            re.IGNORECASE | re.DOTALL,
        ):
            detail = code
        for key, value in instance.values.items():
            if value and re.search(r"PASSWORD|SECRET|TOKEN|CREDENTIAL|(?:API|ACCESS)_KEY", key):
                for secret in {value, quote(value, safe=""), quote_plus(value, safe="")}:
                    detail = detail.replace(secret, "***")
        detail = re.sub(r"(://[^\s/:@]+:)[^\s/@]+(@)", r"\1***\2", detail)
        detail = re.sub(
            r"(?i)((?:password|passwd|pwd|secret(?:_key)?|access_token|api[_-]?key|token)"
            r"\s*(?:=|:|\s)\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
            r"\1***",
            detail,
        )
    return {"type": type(exc).__name__, "code": code, "message": detail[:2048]}


def recovery_status(instance) -> dict:
    """Read the last upgrade's progress; never repair, restart or roll back services."""
    result = {
        "state": "none",
        "needs_attention": False,
        "journal": str(instance.state / "last-upgrade.json"),
        "automatic_rollback": False,
        "recommendations": [],
    }
    try:
        journal = instance.read_state("last-upgrade.json")
        if not journal:
            return result
        images = journal.get("images", [])
        selected = journal.get("services_selected", [])
        result.update(
            {
                key: journal.get(key)
                for key in (
                    "state",
                    "stage",
                    "active_service",
                    "started_at",
                    "updated_at",
                    "finished_at",
                    "error",
                    "completed_steps",
                    "backups",
                )
            }
        )
        result["stage"] = journal.get("stage", "unknown")
        result["completed_steps"] = journal.get("completed_steps", [])
        result["backups"] = journal.get("backups", [])
        result["services"] = journal.get("service_results", [])
        result["needs_attention"] = journal["state"] in ("running", "error")
        if result["needs_attention"]:
            targets = [name for name in selected if name in SERVICES]
            versions = {
                record["service"]: record.get("version", "").split("@", 1)[0]
                for record in images
                if isinstance(record, dict) and record.get("service") in targets
            }
            retries = []
            for name in targets:
                command = ["dev-infra", "upgrade", name]
                if versions.get(name):
                    command.extend(["--to", versions[name]])
                command.append("--backup" if journal.get("backup", True) else "--no-backup")
                retries.append(command)
            result["recommendations"] = [
                {"action": "inspect_services", "argv": ["dev-infra", "list", *targets]},
                *(
                    {"action": "inspect_logs", "argv": ["dev-infra", "logs", name]}
                    for name in targets
                ),
                *({"action": "retry_upgrade", "argv": command} for command in retries),
            ]
            if any(name in ("mysql", "postgres") for name in targets):
                result["recommendations"].append({"action": "avoid_database_downgrade", "argv": []})
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result.update(
            state="invalid",
            needs_attention=True,
            error=_upgrade_error(exc, instance),
            recommendations=[{"action": "inspect_upgrade_journal", "argv": []}],
        )
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
    try:
        docker.instance.read_state("volumes.json")
        records.append({"check": "volume_records", "state": "ok"})
    except (InfraError, OSError) as exc:
        records.append({"check": "volume_records", "state": "error", "detail": str(exc)})
    recovery = recovery_status(docker.instance)
    records.append(
        {
            "check": "upgrade_recovery",
            "state": "error"
            if recovery["state"] in ("error", "invalid")
            else "warning"
            if recovery["needs_attention"]
            else "skipped"
            if recovery["state"] == "none"
            else "ok",
        }
    )
    return {
        "complete": all(r["state"] != "error" for r in records),
        "checks": records,
        "recovery": recovery,
    }


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
    # Unknown or damaged progress is diagnosed, never silently replaced by a retry.
    previous = docker.instance.read_state("last-upgrade.json")
    changes = [record for record in proposal["images"] if record["change"]]
    if not changes:
        # A successful retry can discover that the previous cutover already succeeded.
        # Do not create a journal for an ordinary no-op or clear another service's failure.
        if (
            isinstance(previous, dict)
            and previous.get("state") in ("running", "error")
            and isinstance(previous.get("services_selected"), list)
            and previous["services_selected"]
            and all(isinstance(name, str) for name in previous["services_selected"])
            and set(previous["services_selected"]) <= set(proposal["services_selected"])
        ):
            with docker.instance.lock():
                if docker.instance.signature() != proposal["instance_signature"]:
                    raise InfraError("plan_changed")
                previous.update(
                    state="unchanged",
                    stage="complete",
                    active_service=None,
                    error=None,
                    updated_at=_upgrade_time(),
                    finished_at=_upgrade_time(),
                    resolution="verified_current",
                    service_results=[
                        {
                            "service": record["service"],
                            "target": record["target"],
                            "state": "complete",
                            "completed_steps": ["verify_current"],
                        }
                        for record in proposal["images"]
                    ],
                )
                docker.instance.save_state("last-upgrade.json", previous)
        return {**proposal, "state": "unchanged"}
    with docker.instance.lock():
        stamp = _upgrade_time()
        journal = {
            **proposal,
            "state": "running",
            "stage": "validate",
            "active_service": None,
            "started_at": stamp,
            "updated_at": stamp,
            "finished_at": None,
            "error": None,
            "completed_steps": [],
            "backups": [],
            "service_results": [
                {
                    "service": record["service"],
                    "target": record["target"],
                    "state": "pending",
                    "completed_steps": [],
                }
                for record in changes
            ],
        }
        results = {record["service"]: record for record in journal["service_results"]}

        def save(stage=None, active_service=None):
            if stage is not None:
                journal["stage"] = stage
            journal["active_service"] = active_service
            journal["updated_at"] = _upgrade_time()
            docker.instance.save_state("last-upgrade.json", journal)

        try:
            save("validate")
            # Regenerate local validation while preserving the reviewed remote targets.
            if docker.instance.signature() != proposal["instance_signature"]:
                raise InfraError("plan_changed")
            docker.config()
            docker.validate_data(proposal["services_selected"])
            docker.instance.initialize()
            journal["completed_steps"].append("validate")
            save("backup" if proposal["backup"] else "skip_backup")
            if proposal["backup"]:
                databases = [r["service"] for r in changes if r["service"] in ("mysql", "postgres")]
                for name in databases:
                    save("backup", name)
                    backups = data.backup(docker, [name])
                    journal["backups"].extend(
                        {key: record[key] for key in ("service", "state", "path") if key in record}
                        for record in backups
                    )
                    save("backup", name)
                    if not backups or any(record["state"] != "complete" for record in backups):
                        raise InfraError("backup_unavailable")
                    results[name]["backup_path"] = backups[0]["path"]
                    results[name]["completed_steps"].append("backup")
                    save("backup", name)
            journal["completed_steps"].append("backup" if proposal["backup"] else "skip_backup")
            save("pull")
            # Pull everything before altering declarations or restarting any service.
            for record in changes:
                name = record["service"]
                results[name]["state"] = "pulling"
                save("pull", name)
                docker.run("pull", record["target"], timeout=600)
                results[name]["state"] = "pulled"
                results[name]["completed_steps"].append("pull")
                save("pull", name)
            journal["completed_steps"].append("pull")
            save("save_versions")
            docker.instance.save_versions({r["version_key"]: r["version"] for r in changes})
            journal["completed_steps"].append("save_versions")
            for record in results.values():
                record["completed_steps"].append("save_versions")
            targets = [r["service"] for r in changes if r["service"] in SERVICES]
            if not targets and any(r["service"] == "s3-client" for r in changes):
                targets = ["s3"]
            for record in results.values():
                record["state"] = "applying"
            # Compose's up --wait performs recreation and readiness checks in one call.
            save("recreate")
            docker.ensure_volumes(targets)
            docker.up(targets, settings.wait_timeout)
            journal["completed_steps"].extend(["recreate", "healthcheck"])
            for record in results.values():
                record["state"] = "complete"
                record["completed_steps"].extend(
                    ["recreate", "healthcheck"] if record["service"] in SERVICES else ["activate"]
                )
            journal["state"] = "complete"
            journal["finished_at"] = _upgrade_time()
            save("complete")
        except BaseException as exc:
            journal["state"] = "error"
            journal["finished_at"] = _upgrade_time()
            journal["error"] = _upgrade_error(exc, docker.instance)
            active = journal["active_service"]
            if active in results:
                results[active].update(state="error", error=journal["error"])
                if journal["stage"] == "backup" and not any(
                    record["service"] == active for record in journal["backups"]
                ):
                    journal["backups"].append({"service": active, "state": "error"})
            if journal["stage"] == "recreate":
                try:
                    containers = docker.service_containers()
                except InfraError, OSError, ValueError, subprocess.SubprocessError:
                    containers = {}
                for record in results.values():
                    container = containers.get(record["service"], {})
                    state = container.get("State", {})
                    image = container.get("Config", {}).get("Image")
                    health = state.get("Health", {}).get("Status", "unknown")
                    record.update(
                        state="error",
                        error=journal["error"],
                        runtime_image=image,
                        container_state=state.get("Status", "unknown"),
                        health=health,
                    )
                    if (
                        image == record["target"]
                        and state.get("Status") == "running"
                        and health in ("healthy", "unknown")
                    ):
                        record.update(state="complete", error=None)
                        record["completed_steps"].extend(["recreate", "healthcheck"])
            try:
                save(journal["stage"], active)
            except (OSError, ValueError) as journal_error:
                exc.add_note("Upgrade journal could not be saved: " + type(journal_error).__name__)
            raise
        return journal


def reset(docker, settings, targets: list[str], *, yes: bool) -> dict:
    if len(targets) != 1:
        raise InfraError("one_target")
    if not yes:
        raise InfraError("confirm_required")
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


def verify_source(source: Path) -> dict:
    from .source import verify_source as verify

    return verify(source)


def _scoop_installation() -> bool:
    root = ROOT.resolve()
    return (
        os.name == "nt"
        and (root / "install.json").is_file()
        and root.parent.name == "dev-infra"
        and root.parent.parent.name == "apps"
    )


def _deploy_controller(checkout: Path, preferences, channel: str) -> dict:
    verify_source(checkout)
    if os.name == "nt":
        command = [
            "pwsh",
            "-NoProfile",
            "-File",
            str(checkout / "scripts/install.ps1"),
            "-Distro",
            preferences.distro,
        ]
    else:
        if os.geteuid() != 0:
            raise InfraError("root_required")
        command = ["bash", str(checkout / "scripts/install.sh")]
    result = subprocess.run(command, check=False, stdout=sys.stderr, stderr=sys.stderr)
    if result.returncode:
        raise InfraError(f"install_failed|{result.returncode}")
    return {"state": "complete", "source": str(checkout), "channel": channel}


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
            "channel": "scoop"
            if _scoop_installation()
            else "git"
            if (ROOT / ".source").exists() or (ROOT / ".git").exists()
            else "release"
            if (ROOT / ".release.json").exists()
            else "unknown",
        }
    if os.name != "nt" and os.geteuid() != 0:
        raise InfraError("root_required")
    if action == "upgrade" and source is None and _scoop_installation():
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop'; & scoop update dev-infra; exit $LASTEXITCODE",
            ],
            check=False,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
        if result.returncode:
            raise InfraError(f"install_failed|{result.returncode}")
        return {"state": "complete", "channel": "scoop"}
    checkout = (
        Path(source).expanduser()
        if source
        else Path((ROOT / ".source").read_text(encoding="utf-8").strip())
        if (ROOT / ".source").exists()
        else ROOT
    )
    if not checkout.exists():
        raise InfraError("source_missing")
    checkout = checkout.resolve()
    verified = verify_source(checkout)
    channel = verified["channel"]
    if action == "upgrade" and channel == "git":
        refresh_checkout(checkout)
    elif action == "upgrade" and source is None:
        import tempfile

        from .source import download_release

        with tempfile.TemporaryDirectory(prefix="dev-infra-release-") as temporary:
            package = download_release(Path(temporary))
            deployed = _deploy_controller(package, settings, "release")
        # The downloaded source is temporary; status reads the installed receipt.
        return {**deployed, "source": "https://github.com/hhhxxxddd/dev-infra/releases/latest"}
    return _deploy_controller(checkout, settings, channel)


def refresh_checkout(checkout: Path) -> None:
    """Only fast-forward an unchanged branch tracking the reviewed origin."""
    verify_source(checkout)
    prefix = ["git", "-c", f"safe.directory={checkout}", "-C", str(checkout)]

    def git(*arguments: str) -> str:
        result = subprocess.run(
            [*prefix, *arguments], capture_output=True, text=True, timeout=120, check=False
        )
        if result.returncode:
            raise InfraError("source_update_failed")
        return result.stdout.strip()

    if git("status", "--porcelain"):
        raise InfraError("source_dirty")
    branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
    if git("config", f"branch.{branch}.remote") != "origin":
        raise InfraError("source_tracking_required")
    reference = git("config", f"branch.{branch}.merge")
    if not reference.startswith("refs/heads/"):
        raise InfraError("source_tracking_required")
    git("fetch", "--no-tags", "origin", reference)
    git("merge", "--ff-only", "FETCH_HEAD")
    verify_source(checkout)
