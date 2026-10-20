"""Real S3 helper cleanup and restart checks using isolated, disposable storage."""

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from dev_infra import InfraError, operations
from dev_infra.docker import Docker, managed_volume_service
from dev_infra.instance import Instance
from dev_infra.settings import Settings


def main():
    identity = "dev-infra-s3-smoke-" + uuid4().hex[:12]
    volume = identity + "-data"
    os.environ["COMPOSE_PROJECT_NAME"] = identity
    with tempfile.TemporaryDirectory(prefix=identity) as temporary:
        root = Path(temporary)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, root / name)
        shutil.copytree(REPOSITORY / "config", root / "config")
        (root / ".env").write_text(f"S3_DATA_VOLUME={volume}\n", encoding="utf-8")
        docker = Docker(Instance(root))
        preferences = Settings(root / "config.toml", wait_timeout=60)
        docker.require()
        config = docker.config()
        assert config["name"] == identity
        config["services"] = {
            name: config["services"][name] for name in ("s3", "s3-permissions", "s3-client")
        }
        config["volumes"] = {"s3_data": config["volumes"]["s3_data"]}
        config["services"]["s3"]["ports"] = []
        for service in config["services"].values():
            if docker.image(service["image"]) is None:
                raise RuntimeError("Install the declared RustFS and client images before this test")
            service["pull_policy"] = "never"
        if docker.run("volume", "inspect", volume, check=False).returncode == 0:
            raise RuntimeError("The isolated fixture volume already exists")

        def write_config():
            (root / "compose.yaml").write_text(json.dumps(config), encoding="utf-8")

        def healthy_without_helper():
            containers = docker.service_containers()
            assert containers["s3"]["State"]["Health"]["Status"] == "healthy"
            assert "s3-permissions" not in containers
            assert "s3-client" not in containers
            return containers["s3"]

        def marker():
            return docker.compose("exec", "-T", "s3", "cat", "/data/.helper-smoke").stdout.strip()

        write_config()
        try:
            operations.lifecycle(docker, preferences, "start", ["s3"])
            first = healthy_without_helper()
            docker.compose("exec", "-T", "s3", "sh", "-c", "printf retained > /data/.helper-smoke")
            operations.lifecycle(docker, preferences, "start", ["s3"])
            repeated = healthy_without_helper()
            assert repeated["Id"] == first["Id"]
            assert repeated["State"]["StartedAt"] == first["State"]["StartedAt"]
            assert marker() == "retained"

            operations.lifecycle(docker, preferences, "stop", ["s3"])
            operations.lifecycle(docker, preferences, "start", ["s3"])
            assert healthy_without_helper()["Id"] == first["Id"]
            assert marker() == "retained"
            operations.lifecycle(docker, preferences, "restart", ["s3"])
            assert healthy_without_helper()["Id"] != first["Id"]
            assert marker() == "retained"

            operations.lifecycle(docker, preferences, "remove", ["s3"])
            config["services"]["s3-permissions"]["command"] = ["exit 23"]
            write_config()
            try:
                operations.lifecycle(docker, preferences, "start", ["s3"])
            except InfraError:
                failed = docker.service_containers()["s3-permissions"]
                assert failed["State"]["ExitCode"] == 23
            else:
                raise AssertionError("Failed permissions initialization must block S3 startup")
            config["services"]["s3-permissions"]["command"] = ["chown -R 10001:10001 /data"]
            write_config()
            operations.lifecycle(docker, preferences, "start", ["s3"])
            healthy_without_helper()
            assert marker() == "retained"
            print(
                "PASS: S3 helper cleanup, repeat start, stop/start, recreate, failure/retry, retained data"
            )
        finally:
            docker.compose("down", "--remove-orphans", check=False)
            inspection = docker.run("volume", "inspect", volume, check=False)
            if inspection.returncode == 0:
                metadata = json.loads(inspection.stdout)[0]
                if managed_volume_service(metadata, root) != "s3":
                    raise RuntimeError(
                        "Refusing to remove a fixture volume without ownership labels"
                    )
                docker.run("volume", "rm", volume)


if __name__ == "__main__":
    main()
