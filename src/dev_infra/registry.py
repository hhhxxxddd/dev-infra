"""Read-only Docker Hub stable releases, bounded requests and pagination."""

import json
import re
import urllib.parse
import urllib.request

from . import InfraError

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
STABLE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?$")


def numbers(tag: str) -> tuple[int, ...]:
    match = STABLE.fullmatch(tag)
    if not match:
        raise InfraError(f"invalid_version|{tag}")
    return tuple(int(v) for v in match.groups() if v is not None)


class Registry:
    def get(self, repository: str, suffix: str) -> dict:
        url = f"https://hub.docker.com/v2/repositories/{repository}/tags/{suffix}"
        request = urllib.request.Request(url, headers={"User-Agent": "dev-infra/0.2"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise InfraError(f"invalid_registry|{repository}")
        return data

    def validate(self, repository: str, data: dict) -> dict:
        if (
            not isinstance(data.get("name"), str)
            or not isinstance(data.get("digest"), str)
            or not DIGEST.fullmatch(data["digest"])
        ):
            raise InfraError(f"invalid_registry|{repository}")
        images = data.get("images") or []
        if not isinstance(images, list) or any(not isinstance(value, dict) for value in images):
            raise InfraError(f"invalid_registry|{repository}")
        return {
            "name": data["name"],
            "digest": data["digest"],
            "images": [
                {"digest": value["digest"]}
                for value in images
                if isinstance(value.get("digest"), str) and DIGEST.fullmatch(value["digest"])
            ],
        }

    def exact(self, repository: str, tag: str) -> dict:
        numbers(tag)
        data = self.get(repository, urllib.parse.quote(tag, safe=""))
        if not isinstance(data, dict) or data.get("name") != tag:
            raise InfraError(f"invalid_registry|{repository}")
        return self.validate(repository, data)

    def latest(self, service, version: str) -> dict:
        scope = service.scope(version)
        alias = scope if service.name in ("mysql", "postgres", "redis", "mailpit") else "latest"
        release_digest = self.get(service.repository, alias).get("digest", "")
        if not isinstance(release_digest, str) or not DIGEST.fullmatch(release_digest):
            raise InfraError(f"invalid_registry|{service.repository}")
        candidates = []
        for page in range(1, 11):
            query = urllib.parse.urlencode({"page_size": 100, "name": scope, "page": page})
            payload = self.get(service.repository, "?" + query)
            if not isinstance(payload.get("results"), list):
                raise InfraError(f"invalid_registry|{service.repository}")
            candidates.extend(
                self.validate(service.repository, record)
                for record in payload["results"]
                if isinstance(record, dict)
                and isinstance(record.get("name"), str)
                and STABLE.fullmatch(record["name"])
                and len(numbers(record["name"])) == service.release_parts
                and (record["name"] == scope or record["name"].startswith(scope + "."))
            )
            matched = [r for r in candidates if r["digest"] == release_digest]
            if matched:
                return max(matched, key=lambda r: numbers(r["name"]))
            if not payload.get("next"):
                break
        else:
            raise InfraError(f"incomplete_registry|{service.repository}")
        if not candidates:
            raise InfraError(f"no_release|{service.repository}:{scope}")
        return max(candidates, key=lambda r: numbers(r["name"]))
