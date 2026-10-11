"""Streaming backups and ownership-scoped volume operations."""

import gzip
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from uuid import uuid4

from . import InfraError
from .catalog import LEGACY_VOLUMES, SERVICES
from .instance import read_env


def backup(docker, targets: list[str]) -> list[dict]:
    if any(name not in ("mysql", "postgres") for name in targets):
        raise InfraError("db_only")
    containers = docker.service_containers()
    results = []
    for name in targets:
        if containers.get(name, {}).get("State", {}).get("Status") != "running":
            results.append({"service": name, "state": "skipped"})
            continue
        folder = docker.instance.root / "backup"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        output = folder / f"{name}-{stamp}-{uuid4().hex[:8]}.sql.gz"
        command = ["exec", "-T"]
        environment = {**os.environ, **docker.instance.values}
        if name == "mysql":
            environment["MYSQL_PWD"] = docker.instance.values["MYSQL_ROOT_PASSWORD"]
            command.extend(
                [
                    "-e",
                    "MYSQL_PWD",
                    name,
                    "mysqldump",
                    "-uroot",
                    "--all-databases",
                    "--routines",
                    "--events",
                    "--triggers",
                    "--single-transaction",
                ]
            )
        else:
            command.extend([name, "pg_dumpall", "-U", docker.instance.values["POSTGRES_USER"]])
        argv = docker.compose_argv(*command)
        temporary = output.with_suffix(output.suffix + ".tmp")
        try:
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "wb") as raw, tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(
                    argv,
                    env=environment,
                    cwd=docker.instance.root,
                    stdout=subprocess.PIPE,
                    stderr=errors,
                )
                try:
                    with gzip.GzipFile(fileobj=raw, mode="wb") as compressed:
                        shutil.copyfileobj(process.stdout, compressed)
                    if process.wait():
                        errors.seek(0)
                        raise InfraError(
                            "docker_failed|" + errors.read().decode("utf-8", errors="replace")
                        )
                finally:
                    process.stdout.close()
                    if process.poll() is None:
                        process.terminate()
                        process.wait()
            temporary.replace(output)
            results.append({"service": name, "state": "complete", "path": str(output)})
        finally:
            temporary.unlink(missing_ok=True)
    return results


def volumes(docker, targets: list[str]) -> list[dict]:
    names = docker.run("volume", "ls", "--quiet").stdout.split()
    if not names:
        return []
    metadata = json.loads(docker.run("volume", "inspect", *names).stdout)
    sizes = {
        v["Name"]: v["Size"]
        for v in json.loads(
            docker.run("system", "df", "-v", "--format", "{{json .Volumes}}").stdout
        )
    }
    active = {docker.instance.values[s.volume_key]: s.name for s in SERVICES.values()}
    baseline = read_env(docker.instance.root / "versions.env")
    original = {baseline[s.volume_key]: s.name for s in SERVICES.values()}
    known = {**LEGACY_VOLUMES, **original, **docker.instance.read_state("volumes.json"), **active}
    records = []
    for volume in metadata:
        name = volume["Name"]
        labels = volume.get("Labels") or {}
        owned = labels.get("io.dev-infra.managed") == "true" and labels.get(
            "io.dev-infra.instance"
        ) == str(docker.instance.root)
        service = known.get(name) or (labels.get("io.dev-infra.service") if owned else None)
        if isinstance(service, dict):
            service = service["service"]
        if service not in targets:
            continue
        users = docker.volume_users(name)
        records.append(
            {
                "service": service,
                "volume": name,
                "state": "active" if name in active else "referenced" if users else "obsolete",
                "size": sizes.get(name, "-"),
                "users": users,
                "mountpoint": volume["Mountpoint"],
            }
        )
    return records


def prune(docker, records: list[dict]) -> list[str]:
    removed = []
    for record in records:
        if record["state"] != "obsolete":
            continue
        # Recheck references and declarations immediately before deletion; no force.
        name = record["volume"]
        if name in {
            docker.instance.values[s.volume_key] for s in SERVICES.values()
        } or docker.volume_users(name):
            raise InfraError(f"volume_busy|{name}")
        docker.run("volume", "rm", name)
        removed.append(name)
    return removed
