import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, cli, data, operations, planning, settings
from dev_infra.instance import STATE_FORMAT_VERSION, Instance
from dev_infra.presentation import JSON_SCHEMA_VERSION
from tests.support import FakeDocker, FakeRegistry

REPOSITORY = Path(__file__).resolve().parents[1]


class CliContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        shutil.copytree(REPOSITORY / "config", self.root / "config")
        (self.root / "config/mysql/my.cnf").chmod(0o644)
        self.preferences = self.root / "preferences.toml"
        self.instance = Instance(self.root)
        self.docker = FakeDocker(self.instance)
        self.forward = cli.forward
        for target, name, value in (
            (cli, "ROOT", self.root),
            (cli, "Docker", self.docker),
        ):
            patcher = (
                patch.object(target, name, return_value=value)
                if name == "Docker"
                else patch.object(target, name, value)
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (
            patch.object(cli, "forward", return_value=None),
            patch.object(cli, "Registry", FakeRegistry),
            patch.object(Instance, "lock", side_effect=contextlib.nullcontext),
            patch.dict(os.environ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("DEV_INFRA_TRANSPORT_LANGUAGE", None)

    def invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = cli.main(["--config", str(self.preferences), *arguments])
        # json.loads rejects leading/trailing logs and a second JSON document.
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["schema_version"], JSON_SCHEMA_VERSION)
        return code, payload, errors.getvalue()

    def error(self, arguments, expected_code, expected_error):
        code, payload, _ = self.invoke(*arguments, "--json")
        self.assertEqual(code, expected_code)
        self.assertEqual(payload["error"]["code"], expected_error)
        self.assertEqual(set(payload["error"]), {"code", "message", "details"})
        self.assertIsInstance(payload["error"]["message"], str)
        self.assertIsInstance(payload["error"]["details"], dict)
        return payload

    def test_success_payloads_preserve_business_fields_and_stable_identifiers(self):
        observed = []
        for language in ("zh", "en"):
            self.preferences.write_text(f'language = "{language}"\n', encoding="utf-8")
            code, payload, errors = self.invoke("list", "--json")
            self.assertEqual(code, 0, errors)
            self.assertEqual(set(payload), {"complete", "services", "schema_version"})
            self.assertEqual(
                set(payload["services"][0]), {"service", "state", "image", "endpoint", "volume"}
            )
            observed.append(payload)
            code, payload, _ = self.invoke("check", "mysql", "--updates", "--json")
            self.assertEqual(code, 0)
            self.assertEqual(payload["images"][0]["state"], "update_available")
            self.assertEqual(payload["mode"], "check")
            self.assertFalse(self.instance.state.exists())
        self.assertEqual(observed[0], observed[1])

    def test_argument_errors_use_two_and_never_access_transport_or_docker(self):
        for arguments, error in (
            (("list", "--unknown"), "invalid_arguments"),
            (("list", "unknown-service"), "unknown_service"),
            (("upgrade", "postgres", "--to", "invalid"), "invalid_version"),
            (("upgrade", "all", "--to", "18.7"), "one_target"),
            (("check", "--backup"), "updates_options_required"),
            (("data", "backup", "redis"), "db_only"),
            (("--config=",), "invalid_arguments"),
            (("--config",), "invalid_arguments"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(cli, "forward", side_effect=AssertionError("invalid transport")),
                patch.object(cli, "Docker", side_effect=AssertionError("invalid Docker access")),
            ):
                self.error(arguments, 2, error)
        self.assertFalse(self.instance.state.exists())

    def test_invalid_config_is_structured_before_parsing_or_side_effects(self):
        self.preferences.write_text("invalid toml", encoding="utf-8")
        before = self.preferences.read_bytes()
        with patch.object(cli, "forward", side_effect=AssertionError("invalid config transport")):
            self.error(("list",), 1, "invalid_config")
        self.assertEqual(self.preferences.read_bytes(), before)
        self.assertFalse(self.instance.state.exists())

    def test_execution_blocked_partial_and_interrupt_results(self):
        self.docker.available_flag = False
        self.error(("list",), 1, "docker_unavailable")
        self.docker.available_flag = True
        self.error(("check", "--updates", "postgres", "--to", "19.1"), 1, "migration_required")
        self.docker.entries["mysql"]["State"]["Status"] = "exited"
        payload = self.error(("data", "backup", "mysql"), 1, "partial_result")
        self.assertEqual(payload["backups"], [{"service": "mysql", "state": "skipped"}])
        with patch.object(operations, "overview", side_effect=KeyboardInterrupt()):
            self.error(("list",), 130, "operation_interrupted")
        with patch.object(operations, "overview", side_effect=InfraError("command_timeout")):
            self.error(("list",), 1, "command_timeout")

    def test_messages_may_translate_but_codes_keys_and_details_do_not(self):
        observed = []
        for language in ("zh", "en"):
            self.preferences.write_text(f'language = "{language}"\n', encoding="utf-8")
            payload = self.error(("list", "unknown-service"), 2, "unknown_service")
            payload["error"].pop("message")
            observed.append(payload)
        self.assertEqual(observed[0], observed[1])

    def test_python_logs_and_self_update_diagnostics_go_to_stderr(self):
        def status(*_args):
            print("fixture diagnostic")
            return {"state": "complete", "channel": "git"}

        with patch.object(operations, "self_command", side_effect=status):
            code, payload, errors = self.invoke("self", "update", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(payload["channel"], "git")
        self.assertIn("fixture diagnostic", errors)

    def test_editor_redirects_only_json_stdout_and_keeps_interactive_stdin(self):
        with patch.object(
            settings.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as editor:
            self.invoke("config", "edit", "--json")
            self.assertIsNotNone(editor.call_args.kwargs["stdout"])
            self.assertNotIn("stdin", editor.call_args.kwargs)
        with patch.object(
            settings.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
        ) as editor:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["--config", str(self.preferences), "config", "edit"]), 0)
            self.assertIsNone(editor.call_args.kwargs["stdout"])

    def test_error_details_redact_known_and_embedded_credentials(self):
        secret = self.instance.values["MYSQL_ROOT_PASSWORD"]
        with patch.object(
            operations,
            "overview",
            side_effect=InfraError(
                "docker_failed|" + secret + " https://user:hidden@example.invalid"
            ),
        ):
            payload = self.error(("list",), 1, "docker_failed")
        encoded = json.dumps(payload)
        self.assertNotIn(secret, encoded)
        self.assertNotIn("hidden", encoded)

    def test_logs_and_compose_output_switches_remain_unwrapped(self):
        self.assertFalse(cli.json_requested(["compose", "ps", "--json"]))
        self.assertFalse(cli.json_requested(["logs", "--json"]))
        output, errors = io.StringIO(), io.StringIO()
        with (
            patch.object(
                self.docker,
                "compose",
                side_effect=lambda *_args, **_kwargs: print("raw compose output"),
            ),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(
                cli.main(["--config", str(self.preferences), "compose", "ps", "--json"]), 0
            )
        self.assertEqual(output.getvalue(), "raw compose output\n")
        self.assertFalse(errors.getvalue())

    def test_forward_accepts_one_versioned_json_and_rejects_invalid_backend_output(self):
        preferences = settings.Settings(self.preferences)
        output, errors = io.StringIO(), io.StringIO()
        result = subprocess.CompletedProcess(
            [],
            1,
            json.dumps(
                {
                    "schema_version": 1,
                    "complete": False,
                    "error": {
                        "code": "partial_result",
                        "message": "fixture failure",
                        "details": {},
                    },
                }
            ),
            "fixture log\n",
        )
        with (
            patch.object(cli.os, "name", "nt"),
            patch.object(cli.subprocess, "run", return_value=result),
            contextlib.redirect_stderr(errors),
        ):
            self.assertEqual(self.forward(["list", "--json"], preferences, json_stream=output), 1)
        self.assertFalse(json.loads(output.getvalue())["complete"])
        self.assertEqual(errors.getvalue(), "fixture log\n")
        result.stdout = "raw output"
        with (
            patch.object(cli.os, "name", "nt"),
            patch.object(cli.subprocess, "run", return_value=result),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(InfraError, "transport_failed"),
        ):
            self.forward(["list", "--json"], preferences, json_stream=io.StringIO())


class StateContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-state-contract-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        self.instance = Instance(self.root)
        self.docker = FakeDocker(self.instance)

    def write_raw(self, name, value):
        path = self.instance.state / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_versioned_storage_preserves_business_payloads_and_independent_version(self):
        for name, payload in (
            ("volumes.json", {"old-reference": {"service": "postgres", "scope": "17"}}),
            ("last-upgrade.json", {"state": "error", "services_selected": ["postgres"]}),
        ):
            self.instance.save_state(name, payload)
            stored = json.loads((self.instance.state / name).read_text(encoding="utf-8"))
            self.assertEqual(stored["format"], "dev-infra.state")
            self.assertEqual(stored["format_version"], STATE_FORMAT_VERSION)
            self.assertNotIn("schema_version", stored)
            self.assertEqual(self.instance.read_state(name), payload)

    def test_legacy_records_are_read_without_migration_or_reference_loss(self):
        ledger = {
            "old-reference": "postgres",
            "payload": {"service": "mysql", "scope": "8.4"},
            "format_version": {"service": "redis"},
        }
        for name, payload in (
            ("volumes.json", ledger),
            ("last-upgrade.json", {"state": "running", "services_selected": ["redis"]}),
        ):
            path = self.write_raw(name, payload)
            before = path.read_bytes()
            self.assertEqual(self.instance.read_state(name), payload)
            if name == "last-upgrade.json":
                self.assertTrue(operations.recovery_status(self.instance)["needs_attention"])
            self.assertEqual(path.read_bytes(), before)

    def test_unknown_or_damaged_state_is_diagnosed_and_never_overwritten(self):
        for name in ("volumes.json", "last-upgrade.json"):
            for raw in (
                {"format": "dev-infra.state", "format_version": 999, "payload": {}},
                {"format": "dev-infra.state", "format_version": True, "payload": {}},
                {"format": "dev-infra.state", "format_version": 1, "payload": []},
                [],
            ):
                with self.subTest(name=name, raw=raw):
                    path = self.write_raw(name, raw)
                    before = path.read_bytes()
                    with self.assertRaises(InfraError):
                        self.instance.read_state(name)
                    with self.assertRaises(InfraError):
                        self.instance.save_state(name, {})
                    if name == "last-upgrade.json":
                        self.assertEqual(
                            operations.recovery_status(self.instance)["state"], "invalid"
                        )
                    self.assertEqual(path.read_bytes(), before)

    def test_unknown_ledger_blocks_prune_even_after_an_earlier_preview(self):
        volume = "old-owned-reference"
        self.docker.volume_metadata[volume] = {
            "Name": volume,
            "Labels": {
                "io.dev-infra.managed": "true",
                "io.dev-infra.service": "postgres",
                "io.dev-infra.instance": str(self.root),
            },
            "Mountpoint": "/isolated/fixture",
        }
        records = data.volumes(self.docker, ["postgres"])
        path = self.write_raw(
            "volumes.json", {"format": "dev-infra.state", "format_version": 999, "payload": {}}
        )
        before = path.read_bytes()
        with self.assertRaisesRegex(InfraError, "unsupported_state_version"):
            data.prune(self.docker, records)
        self.assertIn(volume, self.docker.volume_metadata)
        self.assertFalse(any(call[:2] == ["volume", "rm"] for call in self.docker.calls))
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_journal_blocks_upgrade_before_mutations(self):
        proposal = planning.plan(self.docker, FakeRegistry(), ["redis"], to=None, backup=False)
        path = self.write_raw(
            "last-upgrade.json", {"format": "dev-infra.state", "format_version": 999, "payload": {}}
        )
        before = path.read_bytes()
        with self.assertRaisesRegex(InfraError, "unsupported_state_version"):
            operations.upgrade(
                self.docker, settings.Settings(self.root / "preferences.toml"), proposal
            )
        self.assertFalse(self.instance.env_path.exists())
        self.assertFalse(self.instance.overrides_path.exists())
        self.assertFalse(any(call[0] in ("pull", "up") for call in self.docker.calls))
        self.assertEqual(path.read_bytes(), before)

    def test_settings_defaults_round_trip_and_reject_unknown_schema_fields(self):
        path = self.root / "preferences.toml"
        defaults = settings.Settings(path)
        path.write_text(settings.render(defaults), encoding="utf-8")
        self.assertEqual(settings.load(path).data(), defaults.data())
        path.write_text('language="zh"\nunknown=true\n', encoding="utf-8")
        with self.assertRaisesRegex(InfraError, "invalid_config"):
            settings.load(path)


if __name__ == "__main__":
    unittest.main()
