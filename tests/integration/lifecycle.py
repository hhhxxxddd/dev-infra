"""Real Docker lifecycle with an isolated Compose project and disposable Redis volume."""

import shutil
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from dev_infra import operations
from dev_infra.docker import Docker
from dev_infra.instance import Instance
from dev_infra.settings import Settings


def main():
    identity = "dev-infra-smoke-" + uuid4().hex[:12]
    volume = identity + "-redis-data"
    with tempfile.TemporaryDirectory(prefix=identity) as temporary:
        root = Path(temporary)
        for name in (".env.example", "versions.env"):
            shutil.copyfile(REPOSITORY / name, root / name)
        (root / ".env").write_text(f"REDIS_DATA_VOLUME={volume}\n", encoding="utf-8")
        (root / "compose.yaml").write_text(
            f"""name: {identity}
services:
  redis:
    image: redis:${{REDIS_VERSION}}
    pull_policy: never
    volumes:
      - redis_data:/data
    healthcheck:
      test: [CMD, redis-cli, ping]
      interval: 1s
      timeout: 1s
      retries: 20
volumes:
  redis_data:
    external: true
    name: ${{REDIS_DATA_VOLUME}}
""",
            encoding="utf-8",
        )
        docker = Docker(Instance(root))
        preferences = Settings(root / "config.toml", wait_timeout=60)
        docker.require()
        if not docker.image("redis:" + docker.instance.values["REDIS_VERSION"]):
            raise RuntimeError("Install the declared Redis image before running this smoke test")
        try:
            assert (
                operations.lifecycle(docker, preferences, "start", ["redis"])["services"][0][
                    "state"
                ]
                == "healthy"
            )
            docker.compose(
                "exec", "-T", "redis", "redis-cli", "SET", "dev-infra-smoke", "preserved"
            )
            operations.lifecycle(docker, preferences, "restart", ["redis"])
            assert (
                docker.compose(
                    "exec", "-T", "redis", "redis-cli", "GET", "dev-infra-smoke"
                ).stdout.strip()
                == "preserved"
            )
            operations.lifecycle(docker, preferences, "remove", ["redis"])
            assert docker.run("volume", "inspect", volume).returncode == 0
            operations.reset(docker, preferences, ["redis"], yes=True)
            assert (
                docker.compose(
                    "exec", "-T", "redis", "redis-cli", "GET", "dev-infra-smoke"
                ).stdout.strip()
                == ""
            )
            print("PASS: start, health, recreate, data retention, remove, reset")
        finally:
            docker.compose("down", "--remove-orphans", check=False)
            docker.run("volume", "rm", volume, check=False)


if __name__ == "__main__":
    main()
