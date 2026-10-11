import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, data
from dev_infra.docker import Docker
from dev_infra.instance import Instance
from tests.support import FakeDocker

REPOSITORY = Path(__file__).resolve().parents[1]


class VolumeDocker(FakeDocker):
    race_external = False

    def run(self, *args, **kwargs):
        if args[:2] == ("volume", "create"):
            labels = {}
            if not self.race_external:
                for index, value in enumerate(args):
                    if value == "--label":
                        key, label = args[index + 1].split("=", 1)
                        labels[key] = label
            self.volume_metadata.setdefault(
                args[-1],
                {"Name": args[-1], "Labels": labels, "Mountpoint": "/isolated/" + args[-1]},
            )
        return super().run(*args, **kwargs)


class VolumeOwnershipTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-volumes-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        self.instance = Instance(self.root)
        self.docker = VolumeDocker(self.instance)

    def old_volume(self, name="retired-postgres-data", *, managed=True, instance=None):
        labels = (
            {
                "io.dev-infra.managed": "true",
                "io.dev-infra.service": "postgres",
                "io.dev-infra.instance": str(instance or self.root),
                "io.dev-infra.scope": "18",
            }
            if managed
            else {}
        )
        self.docker.volume_metadata[name] = {
            "Name": name,
            "Labels": labels,
            "Mountpoint": "/isolated/" + name,
        }
        return name

    def test_preexisting_external_volume_is_referenced_without_ownership_or_relabeling(self):
        volume = self.instance.values["POSTGRES_DATA_VOLUME"]
        Docker.ensure_volumes(self.docker, ["postgres"])
        record = self.instance.read_state("volumes.json")[volume]
        self.assertEqual(record["ownership"], "external")
        self.assertEqual(self.docker.volume_metadata[volume]["Labels"], {})
        self.assertFalse(any(call[:2] == ["volume", "create"] for call in self.docker.calls))
        listed = data.volumes(self.docker, ["postgres"])
        self.assertEqual(listed[0]["ownership"], "external")
        self.assertEqual(listed[0]["state"], "active")

    def test_created_volume_is_verified_and_recorded_as_managed(self):
        volume = self.instance.values["POSTGRES_DATA_VOLUME"]
        self.docker.volume_metadata.pop(volume)
        Docker.ensure_volumes(self.docker, ["postgres"])
        record = self.instance.read_state("volumes.json")[volume]
        self.assertEqual(record["ownership"], "managed")
        self.assertEqual(record["scope"], "18")
        self.assertEqual(self.docker.calls[-1], ["volume", "inspect", volume])
        self.assertEqual(data.volumes(self.docker, ["postgres"])[0]["ownership"], "managed")

    def test_create_race_does_not_claim_an_external_volume(self):
        volume = self.instance.values["POSTGRES_DATA_VOLUME"]
        self.docker.volume_metadata.pop(volume)
        self.docker.race_external = True
        Docker.ensure_volumes(self.docker, ["postgres"])
        self.assertEqual(self.instance.read_state("volumes.json")[volume]["ownership"], "external")
        self.assertEqual(self.docker.volume_metadata[volume]["Labels"], {})

    def test_old_names_and_legacy_ledger_do_not_authorize_deletion(self):
        legacy = self.old_volume("dev-infra-postgres17-data", managed=False)
        external = self.old_volume("referenced-external-data", managed=False)
        self.instance.save_state(
            "volumes.json",
            {external: {"service": "postgres", "scope": "18", "ownership": "managed"}},
        )
        records = data.volumes(self.docker, ["postgres"])
        selected = [record for record in records if record["volume"] in (legacy, external)]
        self.assertEqual(len(selected), 2)
        self.assertTrue(all(record["state"] == "external" for record in selected))
        self.assertTrue(all(record["ownership"] == "external" for record in selected))
        self.assertEqual(data.prune(self.docker, records), [])
        self.assertIn(legacy, self.docker.volume_metadata)
        self.assertIn(external, self.docker.volume_metadata)

    def test_external_volume_remains_protected_after_configuration_switch(self):
        volume = self.instance.values["POSTGRES_DATA_VOLUME"]
        Docker.ensure_volumes(self.docker, ["postgres"])
        self.instance.values["POSTGRES_DATA_VOLUME"] = "new-postgres-data"
        records = data.volumes(self.docker, ["postgres"])
        old = next(record for record in records if record["volume"] == volume)
        self.assertEqual(old["state"], "external")
        self.assertEqual(data.prune(self.docker, records), [])
        self.assertIn(volume, self.docker.volume_metadata)

    def test_prune_requires_matching_instance_and_service_labels(self):
        own = self.old_volume()
        foreign = self.old_volume("foreign-postgres-data", instance=self.root / "other-instance")
        self.instance.save_state("volumes.json", {foreign: {"service": "postgres"}})
        records = data.volumes(self.docker, ["postgres"])
        self.assertEqual(data.prune(self.docker, records), [own])
        self.assertIn(foreign, self.docker.volume_metadata)
        self.assertIn(self.instance.values["POSTGRES_DATA_VOLUME"], self.docker.volume_metadata)

    def test_prune_rechecks_live_labels_instead_of_a_saved_preview(self):
        volume = self.old_volume()
        records = data.volumes(self.docker, ["postgres"])
        self.docker.volume_metadata[volume]["Labels"] = {}
        self.assertEqual(data.prune(self.docker, records), [])
        self.assertIn(volume, self.docker.volume_metadata)

    def test_prune_rechecks_live_configuration_before_deleting(self):
        volume = self.old_volume()
        records = data.volumes(self.docker, ["postgres"])
        self.instance.env_path.write_text(f"POSTGRES_DATA_VOLUME={volume}\n", encoding="utf-8")
        with self.assertRaisesRegex(InfraError, "volume_busy"):
            data.prune(self.docker, records)
        self.assertIn(volume, self.docker.volume_metadata)

    def test_prune_rechecks_container_references_before_deleting(self):
        volume = self.old_volume()
        records = data.volumes(self.docker, ["postgres"])
        with (
            patch.object(self.docker, "volume_users", return_value=["another-container"]),
            self.assertRaisesRegex(InfraError, "volume_busy"),
        ):
            data.prune(self.docker, records)
        self.assertIn(volume, self.docker.volume_metadata)

    def test_deployment_seeds_references_without_claiming_ownership(self):
        script = (REPOSITORY / "scripts/install.sh").read_text(encoding="utf-8")
        migration = re.search(r"<<'PY'\n(.*?)\nPY", script, re.DOTALL).group(1)
        previous = {"old-reference": {"service": "postgres", "scope": "17"}}
        self.instance.save_state("volumes.json", previous)
        result = subprocess.run(
            [sys.executable, "-", str(self.root)],
            input=migration,
            env={**os.environ, "PYTHONPATH": str(REPOSITORY / "src")},
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = self.instance.read_state("volumes.json")
        self.assertEqual(ledger["old-reference"], previous["old-reference"])
        self.assertEqual(
            ledger[self.instance.values["POSTGRES_DATA_VOLUME"]]["ownership"], "external"
        )


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "Native Bash required")
class MysqlAccountQuotingTests(unittest.TestCase):
    def invoke_fixture(self, root: Path, *, fail=False):
        binary = root / "mysql"
        binary.write_text('#!/usr/bin/env bash\nexec "$TEST_PYTHON" "$TEST_MYSQL_FIXTURE" "$@"\n')
        binary.chmod(0o755)
        fixture = root / "mysql-fixture.py"
        fixture.write_text(
            "import json,os,pathlib,sys\n"
            "request = {'argv':sys.argv[1:], 'sql':sys.stdin.read(), 'password':os.environ['MYSQL_PWD']}\n"
            "pathlib.Path(os.environ['TEST_MYSQL_REQUEST']).write_text(json.dumps(request), encoding='utf-8')\n"
            "if os.environ['TEST_MYSQL_FAIL'] == '1':\n"
            " print(request['sql'], file=sys.stderr)\n"
            " print(request['password'])\n"
            " raise SystemExit(1)\n",
            encoding="utf-8",
        )
        request_path = root / "request.json"
        credentials = {
            "MYSQL_ROOT_PASSWORD": "fixture-root-secret",
            "MYSQL_USER": "dev'\\user",
            "MYSQL_PASSWORD": "quote' slash\\ tick` double\" $() unicode中文",
            "MYSQL_DATABASE": "db`'\\name",
        }
        result = subprocess.run(
            [shutil.which("bash"), str(REPOSITORY / "init/mysql/10-native-auth.sh")],
            env={
                **os.environ,
                **credentials,
                "PATH": str(root) + os.pathsep + os.environ.get("PATH", ""),
                "TEST_PYTHON": sys.executable,
                "TEST_MYSQL_FIXTURE": str(fixture),
                "TEST_MYSQL_REQUEST": str(request_path),
                "TEST_MYSQL_FAIL": str(int(fail)),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        return result, json.loads(request_path.read_text(encoding="utf-8")), credentials

    def test_literals_identifiers_and_backslashes_keep_their_original_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, request, values = self.invoke_fixture(Path(temporary))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'", request["argv"][-1])
        self.assertIn("--binary-mode", request["argv"])
        self.assertIn("--default-character-set=utf8mb4", request["argv"])
        user = "'" + values["MYSQL_USER"].replace("'", "''") + "'"
        password = "'" + values["MYSQL_PASSWORD"].replace("'", "''") + "'"
        database = "`" + values["MYSQL_DATABASE"].replace("`", "``") + "`"
        self.assertEqual(
            request["sql"],
            f"ALTER USER {user}@'%' IDENTIFIED WITH mysql_native_password BY {password};\n"
            f"GRANT ALL PRIVILEGES ON {database}.* TO {user}@'%';\n"
            "FLUSH PRIVILEGES;\n",
        )
        self.assertEqual(request["password"], values["MYSQL_ROOT_PASSWORD"])
        self.assertNotIn(values["MYSQL_ROOT_PASSWORD"], " ".join(request["argv"]))
        self.assertFalse(result.stdout)
        self.assertFalse(result.stderr)

    def test_mysql_failure_cannot_echo_passwords_or_sensitive_sql(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, _, values = self.invoke_fixture(Path(temporary), fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MySQL", result.stderr)
        self.assertFalse(result.stdout)
        for value in values.values():
            self.assertNotIn(value, result.stderr)
        self.assertNotIn("ALTER USER", result.stderr)


if __name__ == "__main__":
    unittest.main()
