"""Real, isolated Docker checks for volume ownership and MySQL account quoting.

Requires an installed mysql:8.4 image. Never pulls images or uses existing volumes,
containers, ports, networks or instance files. All credentials are synthetic.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from dev_infra import InfraError, data
from dev_infra.catalog import SERVICES
from dev_infra.docker import Docker
from dev_infra.instance import Instance, read_env

IMAGE = "mysql:8.4"


class VerificationFailure(Exception):
    """A safe diagnostic that contains no subprocess output or credentials."""


def require(condition, message):
    if not condition:
        raise VerificationFailure(message)


class Fixture:
    def __init__(self):
        self.identity = "dev-infra-correctness-" + uuid4().hex[:12]
        self.containers = []
        self.volumes = []

    def run(self, *arguments, input=None, check=True, timeout=30, environment=None):
        try:
            result = subprocess.run(
                ["docker", *arguments],
                input=input,
                env={**os.environ, **(environment or {})},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise VerificationFailure("isolated Docker command timed out") from None
        if check and result.returncode:
            raise VerificationFailure("isolated Docker command failed")
        return result

    def volume(self, suffix):
        name = self.identity + "-" + suffix
        self.volumes.append(name)
        return name

    def container(self, suffix):
        name = self.identity + "-" + suffix
        self.containers.append(name)
        return name

    def exists(self, name):
        return self.run("volume", "inspect", name, check=False).returncode == 0

    def marker(self, volume, *, write=False):
        name = self.container("marker-" + uuid4().hex[:6])
        result = self.run(
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--name",
            name,
            "--mount",
            f"type=volume,source={volume},target=/fixture",
            "--entrypoint",
            "/bin/sh",
            IMAGE,
            "-c",
            "printf fixture-preserved > /fixture/marker" if write else "cat /fixture/marker",
        )
        if not write:
            require(result.stdout == "fixture-preserved", "external volume data changed")

    def cleanup(self):
        # Only exact names generated and registered by this invocation are eligible.
        for name in reversed(self.containers):
            self.run("rm", "--force", name, check=False)
        failures = []
        for name in reversed(self.volumes):
            self.run("volume", "rm", name, check=False)
            if self.exists(name):
                failures.append(name)
        for name in self.containers:
            if self.run("container", "inspect", name, check=False).returncode == 0:
                failures.append(name)
        require(not failures, "isolated resources remain: " + ", ".join(failures))


def verify_volumes(fixture):
    with tempfile.TemporaryDirectory(prefix=fixture.identity) as temporary:
        root = Path(temporary)
        for name in (".env.example", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, root / name)
        baseline = read_env(REPOSITORY / "versions.env")
        for service in SERVICES.values():
            baseline[service.volume_key] = fixture.identity + "-default-" + service.name
        (root / "versions.env").write_text(
            "".join(f"{key}={value}\n" for key, value in baseline.items()), encoding="utf-8"
        )
        foreign = fixture.volume("foreign")
        idle = fixture.volume("idle")
        referenced = fixture.volume("referenced")
        active = fixture.volume("active")
        fixture.run("volume", "create", foreign)
        fixture.marker(foreign, write=True)

        def select(name):
            (root / ".env").write_text(f"POSTGRES_DATA_VOLUME={name}\n", encoding="utf-8")
            docker = Docker(Instance(root))
            docker.ensure_volumes(["postgres"])
            return docker

        docker = select(foreign)
        require(
            docker.instance.read_state("volumes.json")[foreign]["ownership"] == "external",
            "existing foreign volume was claimed",
        )
        require(
            not json.loads(fixture.run("volume", "inspect", foreign).stdout)[0].get("Labels"),
            "existing foreign volume was relabeled",
        )
        select(idle)
        select(referenced)
        fixture.run(
            "create",
            "--pull=never",
            "--network=none",
            "--name",
            fixture.container("reference"),
            "--mount",
            f"type=volume,source={referenced},target=/fixture",
            "--entrypoint",
            "/bin/true",
            IMAGE,
        )
        docker = select(active)
        # Restrict the prune input even if another instance has similarly named old volumes.
        records = [
            record
            for record in data.volumes(docker, ["postgres"])
            if record["volume"] in fixture.volumes
        ]
        indexed = {record["volume"]: record for record in records}
        require(set(indexed) == {foreign, idle, referenced, active}, "fixture volumes not listed")
        for name, state, ownership in (
            (foreign, "external", "external"),
            (idle, "obsolete", "managed"),
            (referenced, "referenced", "managed"),
            (active, "active", "managed"),
        ):
            require(
                (indexed[name]["state"], indexed[name]["ownership"]) == (state, ownership),
                "volume ownership or state incorrect",
            )
        require(data.prune(docker, records) == [idle], "prune selected unexpected volumes")
        require(not fixture.exists(idle), "idle managed volume was not removed")
        require(
            all(fixture.exists(name) for name in (foreign, referenced, active)),
            "protected volume was removed",
        )
        fixture.marker(foreign)
    print("PASS: external ownership/data preserved; idle removed; active/referenced retained")


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value):
    return "`" + value.replace("`", "``") + "`"


def verify_mysql(fixture):
    root_password = "fixture-simple-root"
    user = "fixture'\\account`"
    database = "fixture`database"
    password = "quote' slash\\ tick` double\" $() unicode中文"
    container = fixture.container("mysql")
    volume = fixture.volume("mysql")
    fixture.run("volume", "create", volume)
    fixture.run(
        "run",
        "--detach",
        "--pull=never",
        "--network=none",
        "--memory=512m",
        "--name",
        container,
        "--env",
        "MYSQL_ROOT_PASSWORD",
        "--mount",
        f"type=volume,source={volume},target=/var/lib/mysql",
        IMAGE,
        "--mysql-native-password=ON",
        environment={"MYSQL_ROOT_PASSWORD": root_password},
    )

    def mysql(sql, *, account="root", secret=root_password, schema=None, check=True):
        options = ["--protocol=socket", "--user=" + account]
        if schema:
            options.append("--database=" + schema)
        return fixture.run(
            "exec",
            "--interactive",
            "--env",
            "MYSQL_PWD",
            container,
            "mysql",
            *options,
            "--batch",
            "--skip-column-names",
            "--default-character-set=utf8mb4",
            "--binary-mode",
            "--init-command=SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'",
            input=sql,
            check=check,
            timeout=10,
            environment={"MYSQL_PWD": secret},
        )

    deadline = time.monotonic() + 90
    while True:
        # The entrypoint starts a temporary server before finishing initialization.
        # Only authenticate once PID 1 has exec'ed the final server.
        process = fixture.run("exec", container, "cat", "/proc/1/comm", check=False)
        if process.returncode == 0 and process.stdout.strip() == "mysqld":
            ready = mysql("SELECT 1;\n", check=False)
            if ready.returncode == 0 and ready.stdout.strip() == "1":
                break
        running = fixture.run("inspect", "--format", "{{.State.Running}}", container)
        require(running.stdout.strip() == "true", "isolated MySQL stopped during initialization")
        require(time.monotonic() < deadline, "isolated MySQL initialization timed out")
        time.sleep(1)
    mysql(
        f"CREATE USER {sql_literal(user)}@'%' IDENTIFIED BY 'fixture-before-change';\n"
        f"CREATE DATABASE {sql_identifier(database)};\n"
    )
    script = (REPOSITORY / "init/mysql/10-native-auth.sh").read_text(encoding="utf-8")

    def initialize(secret):
        return fixture.run(
            "exec",
            "--interactive",
            "--env",
            "MYSQL_ROOT_PASSWORD",
            "--env",
            "MYSQL_USER",
            "--env",
            "MYSQL_PASSWORD",
            "--env",
            "MYSQL_DATABASE",
            container,
            "bash",
            input=script,
            check=False,
            environment={
                "MYSQL_ROOT_PASSWORD": secret,
                "MYSQL_USER": user,
                "MYSQL_PASSWORD": password,
                "MYSQL_DATABASE": database,
            },
        )

    initialized = initialize(root_password)
    require(initialized.returncode == 0, "special-character account initialization failed")
    require(
        not initialized.stdout and not initialized.stderr, "initialization output was not empty"
    )
    authenticated = mysql("SELECT DATABASE();\n", account=user, secret=password, schema=database)
    require(authenticated.stdout.strip() == database, "special-character password login failed")
    # Database privileges and quoted identifier must also work under the new credentials.
    mysql(
        "CREATE TABLE fixture_probe (value INT);\nINSERT INTO fixture_probe VALUES (1);\n",
        account=user,
        secret=password,
        schema=database,
    )
    plugin = mysql(f"SELECT plugin FROM mysql.user WHERE User={sql_literal(user)} AND Host='%';\n")
    require(
        plugin.stdout.strip() == "mysql_native_password", "account authentication plugin differs"
    )
    wrong_password = "fixture-wrong-root-secret"
    failed = initialize(wrong_password)
    require(failed.returncode != 0 and not failed.stdout, "failed authentication was not reported")
    require("MySQL" in failed.stderr, "safe failure diagnostic missing")
    output = failed.stdout + failed.stderr
    require(
        all(
            value not in output
            for value in (root_password, wrong_password, user, password, database)
        )
        and "ALTER USER" not in output,
        "failure diagnostic leaked a credential or SQL statement",
    )
    print(
        "PASS: quoted account/password/database, login, grants, native plugin, safe failure output"
    )


def main():
    fixture = Fixture()
    status = 0
    try:
        fixture.run("image", "inspect", IMAGE)
        verify_volumes(fixture)
        verify_mysql(fixture)
    except VerificationFailure as exc:
        print("FAIL:", exc, file=sys.stderr)
        status = 1
    except (InfraError, OSError, ValueError, KeyError) as exc:
        # Docker/server errors may include SQL; report only the exception type.
        print("FAIL: isolated correctness verification:", type(exc).__name__, file=sys.stderr)
        status = 1
    finally:
        try:
            fixture.cleanup()
            print("PASS: all isolated containers and volumes cleaned up")
        except VerificationFailure as exc:
            print("FAIL:", exc, file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
