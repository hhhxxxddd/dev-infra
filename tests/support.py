from __future__ import annotations

import json
import subprocess
import sys

from dev_infra.catalog import CLIENT, SERVICES
from dev_infra.docker import Docker
from dev_infra.planning import image_repository

DIGEST = "sha256:" + "a" * 64
OLD_DIGEST = "sha256:" + "b" * 64
RELEASES = {
    "mysql": "8.4.11",
    "postgres": "18.6",
    "redis": "8.10.2",
    "kafka": "4.3.1",
    "s3": "1.0.1",
    "s3-client": "v0.1.36",
    "mailpit": "v1.31.4",
}


def metadata(tag):
    return {"name": tag, "digest": DIGEST, "images": [{"digest": DIGEST}]}


class FakeRegistry:
    failure = None

    def latest(self, service, version):
        if service.name == self.failure:
            raise OSError("isolated registry failure")
        return metadata(RELEASES[service.name])

    def exact(self, repository, tag):
        return metadata(tag)


class FakeDocker:
    def __init__(self, instance):
        self.instance = instance
        self.calls = []
        self.current = False
        self.available_flag = True
        self.fail_up = False
        self.fail_pull = False
        self.entries = {name: self.container(name) for name in SERVICES}
        self.volume_metadata = {
            instance.values[s.volume_key]: {
                "Name": instance.values[s.volume_key],
                "Labels": {},
                "Mountpoint": "/isolated/volumes/" + name,
            }
            for name, s in SERVICES.items()
        }

    def container(self, name):
        service = SERVICES[name]
        return {
            "Name": "/dev-" + name + "-1",
            "Image": "old-image",
            "Config": {
                "Image": f"{image_repository(service)}:{self.instance.values[service.version_key]}",
                "Labels": {"com.docker.compose.service": name},
            },
            "State": {"Status": "running", "Health": {"Status": "healthy"}},
        }

    def available(self):
        self.calls.append(["info"])
        return self.available_flag

    def require(self):
        if not self.available_flag:
            from dev_infra import InfraError

            raise InfraError("docker_unavailable")

    def config(self):
        self.calls.append(["config"])
        return {
            "services": {
                s.name: {"image": f"{image_repository(s)}:{self.instance.values[s.version_key]}"}
                for s in (*SERVICES.values(), CLIENT)
            }
        }

    def service_containers(self):
        return self.entries

    def image(self, reference):
        return {"RepoDigests": ["fixture@" + (DIGEST if self.current else OLD_DIGEST)]}

    def run(self, *args, **kwargs):
        self.calls.append(list(args))
        output, code = "", 0
        if args[:2] == ("volume", "ls"):
            output = "\n".join(self.volume_metadata)
        elif args[:2] == ("volume", "inspect"):
            if all(n in self.volume_metadata for n in args[2:]):
                output = json.dumps([self.volume_metadata[n] for n in args[2:]])
            else:
                code = 1
        elif args[:2] == ("volume", "rm"):
            self.volume_metadata.pop(args[2])
        elif args[:2] == ("system", "df"):
            output = json.dumps([{"Name": n, "Size": "1MB"} for n in self.volume_metadata])
        elif args[0] == "pull" and self.fail_pull:
            from dev_infra import InfraError

            raise InfraError("docker_failed|isolated pull failure")
        return subprocess.CompletedProcess(args, code, output, "")

    def compose(self, *args, **kwargs):
        self.calls.append(list(args))
        if args[0] == "stop":
            for name in args[1:]:
                if name in self.entries:
                    self.entries[name]["State"]["Status"] = "exited"
        if args[0] == "rm":
            for name in args:
                self.entries.pop(name, None)
        return subprocess.CompletedProcess(args, 0, "", "")

    def compose_argv(self, *args):
        script = self.instance.root / "dump-fixture.py"
        script.write_text(
            "import os,sys\nprint('-- isolated SQL')\nraise SystemExit(int(os.environ.get('TEST_DUMP_EXIT','0')))\n",
            encoding="utf-8",
        )
        return [sys.executable, str(script)]

    def ensure_volumes(self, targets):
        Docker.ensure_volumes(self, targets)

    def validate_data(self, targets):
        Docker.validate_data(self, targets)

    def data_issues(self, targets, containers=None):
        return Docker.data_issues(self, targets, containers)

    def up(self, targets, wait, *, recreate=False):
        self.calls.append(["up", *targets])
        if self.fail_up:
            from dev_infra import InfraError

            raise InfraError("docker_failed|isolated healthcheck failure")
        for name in targets:
            self.entries[name] = self.container(name)

    def volume_users(self, volume):
        service = next(
            (s.name for s in SERVICES.values() if self.instance.values[s.volume_key] == volume),
            None,
        )
        return [self.entries[service]["Name"].lstrip("/")] if service in self.entries else []
