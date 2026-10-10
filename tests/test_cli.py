from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "a" * 64
IMAGES = {
    "mysql": "mysql:8.4",
    "postgres": "postgres:18",
    "redis": "redis:8",
    "kafka": "apache/kafka:4.3.1",
    "s3": "rustfs/rustfs:1.0.1",
    "s3-client": "rustfs/rc:v0.1.36",
    "mailpit": "axllent/mailpit:v1.31.4",
}
RELEASES = {
    "library/mysql": "8.4.11",
    "library/postgres": "18.6",
    "library/redis": "8.10.2",
    "apache/kafka": "4.3.1",
    "rustfs/rustfs": "1.0.1",
    "rustfs/rc": "v0.1.36",
    "axllent/mailpit": "v1.31.4",
}
FAKE_TOOL = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
from urllib.parse import urlparse, parse_qs
tool = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["TEST_LOG"], "a") as stream:
    stream.write(json.dumps([tool, *args]) + "\n")
digest = "sha256:" + "a" * 64
if tool == "curl":
    url = args[-1]
    repository = url.split("/repositories/")[1].split("/tags")[0]
    if repository == os.environ.get("TEST_REMOTE_FAIL"):
        print("registry unavailable", file=sys.stderr)
        sys.exit(22)
    release = json.loads(os.environ["TEST_RELEASES"])[repository]
    metadata = {"name": release, "digest": digest, "images": [{"digest": digest}]}
    if "?" in url:
        page = parse_qs(urlparse(url).query).get("page", ["1"])[0]
        if os.environ.get("TEST_PAGINATE") and page == "1":
            print(json.dumps({"next": "page2", "results": []}))
        else:
            print(json.dumps({"next": None, "results": [metadata,
                {**metadata, "name": release + "-rc.9"}]}))
    else:
        print(json.dumps(metadata))
elif tool == "backup":
    pass
elif args[:2] == ["image", "inspect"]:
    if os.environ.get("TEST_IMAGE_MISSING"):
        sys.exit(1)
    if args[-1] == "sha256:old":
        digest = "sha256:" + "b" * 64
    print(json.dumps([{"RepoDigests": ["fixture@" + digest]}]))
elif args[:1] == ["inspect"]:
    print("sha256:old")
elif args[:1] == ["compose"] and "config" in args and "--format" in args:
    print(json.dumps({"services": {name: {"image": image}
        for name, image in json.loads(os.environ["TEST_IMAGES"]).items()}}))
elif args[:1] == ["compose"] and "ps" in args and os.environ.get("TEST_RUNNING"):
    print("running-container")
"""


@unittest.skipUnless(os.name == "posix", "Native WSL Bash required")
class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for filename in ("dev-infra", ".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / filename, self.root / filename)
        shutil.copytree(REPOSITORY / "bin", self.root / "bin")
        for path in (self.root / "bin").iterdir():
            path.chmod(0o755)
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        for name in ("docker", "curl"):
            path = fake_bin / name
            path.write_text(FAKE_TOOL)
            path.chmod(0o755)
        backup = self.root / "bin/backup"
        backup.write_text(FAKE_TOOL)
        backup.chmod(0o755)
        self.log = self.root / "commands.jsonl"
        self.environment = {
            **os.environ,
            "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
            "TEST_LOG": str(self.log),
            "TEST_IMAGES": json.dumps(IMAGES),
            "TEST_RELEASES": json.dumps(RELEASES),
        }

    def invoke(self, *arguments, **environment):
        return subprocess.run(
            ["bash", str(self.root / "dev-infra"), *arguments],
            check=False,
            env={**self.environment, **environment},
            capture_output=True,
            text=True,
            timeout=20,
        )

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_outdated_is_read_only_and_ignores_prereleases(self):
        result = self.invoke("outdated", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["complete"])
        self.assertEqual(len(payload["images"]), 7)
        self.assertTrue(all(item["status"] == "current" for item in payload["images"]))
        self.assertEqual(payload["images"][0]["latest"], "mysql:8.4.11")
        self.assertFalse((self.root / ".env").exists())
        self.assertFalse(any(command[0] == "backup" for command in self.commands()))
        for command in self.commands():
            self.assertFalse(
                {"pull", "up", "run", "create", "stop"}.intersection(command)
            )

    def test_outdated_preserves_partial_results_on_registry_failure(self):
        result = self.invoke("outdated", "--json", TEST_REMOTE_FAIL="library/redis")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["complete"])
        self.assertEqual(len(payload["images"]), 7)
        statuses = {item["service"]: item["status"] for item in payload["images"]}
        self.assertEqual(statuses["redis"], "error")
        self.assertEqual(statuses["mysql"], "current")

    def test_outdated_reads_later_pages(self):
        result = self.invoke("outdated", "mysql", "--json", TEST_PAGINATE="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["images"][0]["latest"], "mysql:8.4.11"
        )
        self.assertTrue(any("page=2" in command[-1] for command in self.commands()))

    def test_outdated_compares_running_image_and_handles_missing_image(self):
        for environment, expected in (
            ({"TEST_RUNNING": "1"}, "update_available"),
            ({"TEST_IMAGE_MISSING": "1"}, "not_downloaded"),
        ):
            with self.subTest(expected=expected):
                result = self.invoke("outdated", "mysql", "--json", **environment)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout)["images"][0]["status"], expected
                )

    def test_update_skips_only_explicitly_disabled_backups_and_pulls_s3_client(self):
        for skip in (False, True):
            with self.subTest(skip=skip):
                self.log.unlink(missing_ok=True)
                result = self.invoke(
                    "update", *(["--no-backup"] if skip else []), "all"
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                backups = [
                    command for command in self.commands() if command[0] == "backup"
                ]
                self.assertEqual(len(backups), 0 if skip else 2)
                pulls = [command for command in self.commands() if "pull" in command]
                self.assertEqual(len(pulls), 1)
                self.assertIn("s3-client", pulls[0])

    def test_unknown_option_fails_before_config_or_docker_changes(self):
        result = self.invoke("update", "--no-backups")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())
        self.assertFalse((self.root / ".env").exists())


if __name__ == "__main__":
    unittest.main()
