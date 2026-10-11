from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

from dev_infra import InfraError, operations, planning, settings
from dev_infra.instance import Instance, read_env
from tests.support import FakeDocker, FakeRegistry

REPOSITORY = Path(__file__).resolve().parents[1]


class UpgradeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        mysql = self.root / "config/mysql/my.cnf"
        mysql.parent.mkdir(parents=True)
        shutil.copyfile(REPOSITORY / "config/mysql/my.cnf", mysql)
        self.instance = Instance(self.root)
        self.docker = FakeDocker(self.instance)
        self.settings = settings.Settings(self.root / "preferences.toml")
        self.lock = patch.object(self.instance, "lock", side_effect=nullcontext)
        self.lock.start()
        self.addCleanup(self.lock.stop)

    def plan(self, *targets, backup=False):
        return planning.plan(self.docker, FakeRegistry(), list(targets), to=None, backup=backup)

    def journal(self):
        return self.instance.read_state("last-upgrade.json")

    def test_missing_recovery_is_read_only_and_does_not_inspect_docker(self):
        before = list(self.docker.calls)
        result = operations.recovery_status(self.instance)
        self.assertEqual(result["state"], "none")
        self.assertFalse(result["needs_attention"])
        self.assertFalse(result["automatic_rollback"])
        self.assertEqual(self.docker.calls, before)
        self.assertFalse(self.instance.state.exists())
        self.assertFalse(self.instance.env_path.exists())

    def test_pull_failure_records_stage_and_redacts_passwords_and_url_credentials(self):
        password = "private p@ss/word"
        self.instance.values["MYSQL_ROOT_PASSWORD"] = password
        proposal = self.plan("redis")
        original = self.docker.entries["redis"]["Config"]["Image"]
        failure = InfraError(
            "docker_failed|pull failed "
            + password
            + " "
            + quote(password, safe="")
            + " https://operator:unknown-secret@example.invalid; password='another secret'"
        )
        original_run = self.docker.run

        def run(*args, **kwargs):
            if args[0] == "pull":
                raise failure
            return original_run(*args, **kwargs)

        with patch.object(self.docker, "run", side_effect=run), self.assertRaises(InfraError):
            operations.upgrade(self.docker, self.settings, proposal)
        record = self.journal()
        encoded = json.dumps(record)
        for secret in (password, quote(password, safe=""), "unknown-secret", "another secret"):
            self.assertNotIn(secret, encoded)
        self.assertEqual(record["stage"], "pull")
        self.assertEqual(record["active_service"], "redis")
        self.assertEqual(record["error"]["code"], "docker_failed")
        self.assertEqual(record["completed_steps"], ["validate", "skip_backup"])
        self.assertEqual(record["service_results"][0]["state"], "error")
        self.assertFalse(self.instance.overrides_path.exists())
        self.assertEqual(self.docker.entries["redis"]["Config"]["Image"], original)
        recovery = operations.recovery_status(self.instance)
        self.assertTrue(recovery["needs_attention"])
        retry = next(r for r in recovery["recommendations"] if r["action"] == "retry_upgrade")
        self.assertEqual(
            retry["argv"], ["dev-infra", "upgrade", "redis", "--to", "8.10.2", "--no-backup"]
        )

    def test_completed_first_backup_is_preserved_when_second_dump_fails(self):
        proposal = self.plan("mysql", "postgres", backup=True)
        path = str(self.root / "backup/mysql-complete.sql.gz")

        def backup(_docker, targets):
            if targets == ["mysql"]:
                return [{"service": "mysql", "state": "complete", "path": path}]
            self.assertEqual(self.journal()["backups"][0]["path"], path)
            raise InfraError("docker_failed|postgres dump failed")

        with (
            patch.object(operations.data, "backup", side_effect=backup),
            self.assertRaises(InfraError),
        ):
            operations.upgrade(self.docker, self.settings, proposal)
        record = self.journal()
        self.assertEqual(record["stage"], "backup")
        self.assertEqual(
            record["backups"],
            [
                {"service": "mysql", "state": "complete", "path": path},
                {"service": "postgres", "state": "error"},
            ],
        )
        self.assertEqual(record["service_results"][0]["backup_path"], path)
        self.assertFalse(any(call[0] == "pull" for call in self.docker.calls))
        self.assertFalse(self.instance.overrides_path.exists())

    def test_validation_failure_is_recorded_without_pulling_or_saving_versions(self):
        proposal = self.plan("redis")
        self.instance.env_path.write_text("REDIS_PORT=26380\n", encoding="utf-8")
        with self.assertRaisesRegex(InfraError, "plan_changed"):
            operations.upgrade(self.docker, self.settings, proposal)
        record = self.journal()
        self.assertEqual(record["stage"], "validate")
        self.assertEqual(record["error"]["code"], "plan_changed")
        self.assertFalse(record["completed_steps"])
        self.assertFalse(any(call[0] == "pull" for call in self.docker.calls))
        self.assertFalse(self.instance.overrides_path.exists())

    def test_partial_recreation_reports_each_actual_service_and_keeps_target_versions(self):
        proposal = self.plan("redis", "mysql")

        def up(targets, wait):
            for name in targets:
                self.docker.entries[name] = self.docker.container(name)
            self.docker.entries["mysql"]["State"]["Health"]["Status"] = "unhealthy"
            raise InfraError("docker_failed|mysql did not become healthy")

        with patch.object(self.docker, "up", side_effect=up), self.assertRaises(InfraError):
            operations.upgrade(self.docker, self.settings, proposal)
        record = self.journal()
        self.assertEqual(record["stage"], "recreate")
        self.assertIn("save_versions", record["completed_steps"])
        self.assertNotIn("healthcheck", record["completed_steps"])
        services = {r["service"]: r for r in record["service_results"]}
        self.assertEqual(services["redis"]["state"], "complete")
        self.assertEqual(services["redis"]["health"], "healthy")
        self.assertEqual(services["mysql"]["state"], "error")
        self.assertEqual(services["mysql"]["health"], "unhealthy")
        self.assertIn("MYSQL_VERSION", read_env(self.instance.overrides_path))
        self.assertFalse(any(call[0] in ("stop", "rm") for call in self.docker.calls))
        recovery = operations.recovery_status(self.instance)
        self.assertIn(
            "avoid_database_downgrade", [r["action"] for r in recovery["recommendations"]]
        )

    def test_phase_progress_is_saved_and_successful_retry_clears_failure(self):
        proposal = self.plan("redis")
        self.docker.fail_pull = True
        with self.assertRaises(InfraError):
            operations.upgrade(self.docker, self.settings, proposal)
        self.docker.fail_pull = False
        snapshots = []
        original = self.instance.save_state

        def save(name, value):
            if name == "last-upgrade.json":
                snapshots.append(json.loads(json.dumps(value)))
            original(name, value)

        with patch.object(self.instance, "save_state", side_effect=save):
            result = operations.upgrade(self.docker, self.settings, self.plan("redis"))
        self.assertEqual(result["state"], "complete")
        self.assertIsNone(result["error"])
        self.assertEqual(result["stage"], "complete")
        for field in ("started_at", "updated_at", "finished_at"):
            self.assertIsNotNone(datetime.fromisoformat(result[field]).tzinfo)
        stages = {snapshot["stage"] for snapshot in snapshots}
        self.assertTrue(
            {"validate", "skip_backup", "pull", "save_versions", "recreate", "complete"} <= stages
        )
        pulled = next(
            snapshot
            for snapshot in snapshots
            if snapshot["stage"] == "pull" and snapshot["service_results"][0]["state"] == "pulled"
        )
        self.assertEqual(pulled["active_service"], "redis")
        self.assertFalse(operations.recovery_status(self.instance)["needs_attention"])

    def test_already_healthy_retry_clears_stale_error_without_restart(self):
        self.instance.save_state(
            "last-upgrade.json",
            {
                "state": "error",
                "stage": "recreate",
                "services_selected": ["redis"],
                "error": {"code": "docker_failed"},
                "completed_steps": ["save_versions"],
            },
        )
        self.docker.current = True
        proposal = self.plan("redis")
        self.docker.calls.clear()
        result = operations.upgrade(self.docker, self.settings, proposal)
        self.assertEqual(result["state"], "unchanged")
        self.assertIsNone(self.journal()["error"])
        self.assertEqual(self.journal()["resolution"], "verified_current")
        self.assertFalse(operations.recovery_status(self.instance)["needs_attention"])
        self.assertFalse(self.docker.calls)

    def test_noop_for_other_service_does_not_clear_original_failure(self):
        self.instance.save_state(
            "last-upgrade.json",
            {
                "state": "error",
                "stage": "backup",
                "services_selected": ["mysql"],
            },
        )
        self.docker.current = True
        operations.upgrade(self.docker, self.settings, self.plan("redis"))
        self.assertEqual(self.journal()["state"], "error")

    def test_corrupt_or_incomplete_journal_is_reported_read_only(self):
        path = self.instance.state / "last-upgrade.json"
        path.parent.mkdir()
        for content in (
            "{broken",
            "[]",
            '{"state": "unexpected"}',
            '{"state":"error", "images":[{"version":14}]}',
            '{"state":"error", "error":{"code":[],"message":14}}',
            '{"state":"error", "backups":[1]}',
            '{"state":"error", "service_results":[{"state":14}]}',
            '{"state":"error", "completed_steps":"pull"}',
            '{"state":"error", "stage":14}',
            '{"state":"error", "backups":null}',
        ):
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                before = path.read_bytes()
                result = operations.recovery_status(self.instance)
                self.assertEqual(result["state"], "invalid")
                self.assertTrue(result["needs_attention"])
                self.assertEqual(path.read_bytes(), before)
                self.assertFalse(self.docker.calls)

    def test_check_includes_failed_recovery_and_legacy_running_records(self):
        for state, expected in (("error", "error"), ("running", "warning")):
            self.instance.save_state(
                "last-upgrade.json",
                {
                    "state": state,
                    "services_selected": ["redis"],
                    "completed_steps": ["pull"],
                },
            )
            result = operations.check(self.docker)
            recovery_check = next(r for r in result["checks"] if r["check"] == "upgrade_recovery")
            self.assertEqual(recovery_check["state"], expected)
            self.assertEqual(result["complete"], state != "error")
            self.assertTrue(result["recovery"]["needs_attention"])
            self.assertEqual(result["recovery"]["stage"], "unknown")

    def test_interruption_and_subprocess_errors_never_persist_command_secrets_or_sql(self):
        failures = [
            KeyboardInterrupt(),
            subprocess.TimeoutExpired(["docker", "--password", "unknown secret"], 7),
            subprocess.CalledProcessError(3, ["docker", "--password", "unknown secret"]),
            InfraError("docker_failed|ALTER ROLE dev PASSWORD 'unknown secret';"),
            InfraError("docker_failed|statement: SELECT 'unknown secret' FROM user_data;"),
        ]
        for failure in failures:
            with self.subTest(kind=type(failure).__name__):
                error = operations._upgrade_error(failure, self.instance)
                self.assertNotIn("unknown secret", json.dumps(error))
                self.assertNotIn("ALTER ROLE", error["message"])
                self.assertLessEqual(len(error["message"]), 2048)
        proposal = self.plan("redis")
        with (
            patch.object(self.docker, "run", side_effect=KeyboardInterrupt()),
            self.assertRaises(KeyboardInterrupt),
        ):
            operations.upgrade(self.docker, self.settings, proposal)
        self.assertEqual(self.journal()["error"]["code"], "operation_interrupted")
        self.assertEqual(self.journal()["state"], "error")


if __name__ == "__main__":
    unittest.main()
