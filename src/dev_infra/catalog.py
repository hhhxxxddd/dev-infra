"""Public services and policies; deployment details remain in Compose."""

from dataclasses import dataclass

from . import InfraError


@dataclass(frozen=True)
class Service:
    name: str
    version_key: str
    volume_key: str
    repository: str
    port_key: str
    group: str = "core"
    scope_parts: int = 1
    release_parts: int = 3
    web: bool = False

    def scope(self, version: str) -> str:
        return ".".join(version.split("@", 1)[0].split(".")[: self.scope_parts])


SERVICES = {
    s.name: s
    for s in (
        Service(
            "mysql",
            "MYSQL_VERSION",
            "MYSQL_DATA_VOLUME",
            "library/mysql",
            "MYSQL_PORT",
            scope_parts=2,
        ),
        Service(
            "postgres",
            "POSTGRES_VERSION",
            "POSTGRES_DATA_VOLUME",
            "library/postgres",
            "POSTGRES_PORT",
            release_parts=2,
        ),
        Service("redis", "REDIS_VERSION", "REDIS_DATA_VOLUME", "library/redis", "REDIS_PORT"),
        Service(
            "kafka",
            "KAFKA_VERSION",
            "KAFKA_DATA_VOLUME",
            "apache/kafka",
            "KAFKA_PORT",
            scope_parts=2,
        ),
        Service(
            "s3", "RUSTFS_VERSION", "S3_DATA_VOLUME", "rustfs/rustfs", "S3_PORT", "extra", web=True
        ),
        Service(
            "mailpit",
            "MAILPIT_VERSION",
            "MAILPIT_DATA_VOLUME",
            "axllent/mailpit",
            "MAILPIT_UI_PORT",
            "extra",
            web=True,
        ),
    )
}
CLIENT = Service("s3-client", "RUSTFS_RC_VERSION", "", "rustfs/rc", "", scope_parts=2)
VERSION_KEYS = {s.version_key for s in (*SERVICES.values(), CLIENT)}
LEGACY_VOLUMES = {"dev-infra-postgres17-data": "postgres"}


def resolve(requested: list[str] | tuple[str, ...]) -> list[str]:
    result = []
    for name in requested or ["all"]:
        if name in ("all", "core", "extra"):
            expanded = [s.name for s in SERVICES.values() if name == "all" or s.group == name]
        elif name in SERVICES:
            expanded = [name]
        else:
            raise InfraError(f"unknown_service|{name}")
        result.extend(s for s in expanded if s not in result)
    return result
