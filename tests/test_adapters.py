import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dev_infra import InfraError, cli
from dev_infra.docker import Docker, compose_is_query
from dev_infra.instance import Instance
from dev_infra.presentation import JSON_SCHEMA_VERSION
from dev_infra.settings import Settings

REPOSITORY = Path(__file__).resolve().parents[1]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for filename in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / filename, self.root / filename)
        self.instance = Instance(self.root)

    def test_compose_receives_override_env_file_and_values_without_shell(self):
        self.instance.save_versions({"REDIS_VERSION": "8.10.2"})
        docker = Docker(self.instance)
        completed = subprocess.CompletedProcess([], 0, "{}", "")
        with patch("subprocess.run", return_value=completed) as run:
            docker.compose("config", "--format", "json")
        self.assertIn(str(self.instance.overrides_path), run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["env"]["REDIS_VERSION"], "8.10.2")
        self.assertNotIn("shell", run.call_args.kwargs)

    @unittest.skipUnless(os.name == "posix", "Native WSL locking")
    def test_concurrent_mutations_are_rejected(self):
        with self.instance.lock(), self.assertRaisesRegex(InfraError, "busy"), self.instance.lock():
            self.fail("second mutation acquired the lock")

    def test_compose_queries_preserve_raw_output_without_creating_instance_state(self):
        docker = Docker(self.instance)
        for arguments in (
            ["ps", "--json"],
            ["config"],
            ["logs", "-f"],
            ["images"],
            ["version"],
            ["--profile", "optional", "ps"],
            ["--ansi=never", "config"],
            ["-pfixture", "ps"],
            ["up", "--help"],
            ["--help"],
            [],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(docker, "require"),
                patch.object(docker, "compose") as compose,
                patch.object(self.instance, "lock", side_effect=AssertionError("query lock")),
            ):
                args = SimpleNamespace(command="compose", arguments=arguments)
                self.assertEqual(cli.dispatch(args, None, None, docker), 0)
                compose.assert_called_once_with(*arguments, capture=False, timeout=None)
        self.assertFalse(self.instance.state.exists())
        self.assertFalse(self.instance.env_path.exists())

    def test_compose_mutations_execute_with_the_instance_lock(self):
        docker = Docker(self.instance)
        locked = False

        @contextlib.contextmanager
        def lock():
            nonlocal locked
            locked = True
            try:
                yield
            finally:
                locked = False

        def compose(*_args, **_kwargs):
            self.assertTrue(locked)

        for arguments in (
            ["up", "-d"],
            ["down"],
            ["pull"],
            ["exec", "redis", "command", "--help"],
            ["--profile", "optional", "restart"],
            ["--project-name=fixture", "rm"],
            ["config", "--output", "generated.yaml"],
            ["config", "--output=generated.yaml"],
            ["convert", "-ogenerated.yaml"],
            ["wait", "--down-project"],
            ["future-subcommand"],
        ):
            with (
                self.subTest(arguments=arguments),
                patch.object(docker, "require"),
                patch.object(docker, "compose", side_effect=compose),
                patch.object(self.instance, "lock", side_effect=lock) as operation_lock,
            ):
                args = SimpleNamespace(command="compose", arguments=arguments)
                self.assertEqual(cli.dispatch(args, None, None, docker), 0)
                operation_lock.assert_called_once()
                self.assertFalse(locked)

    @unittest.skipUnless(os.name == "posix", "Native WSL locking")
    def test_compose_mutation_cannot_bypass_a_running_instance_operation(self):
        docker = Docker(self.instance)
        args = SimpleNamespace(command="compose", arguments=["up", "-d"])
        with (
            self.instance.lock(),
            patch.object(docker, "require"),
            patch.object(docker, "compose") as compose,
            self.assertRaisesRegex(InfraError, "busy"),
        ):
            cli.dispatch(args, None, None, docker)
        compose.assert_not_called()

    def test_compose_command_help_does_not_classify_exec_payload_as_read_only(self):
        self.assertTrue(compose_is_query(["exec", "--help"]))
        self.assertFalse(compose_is_query(["exec", "redis", "--help"]))
        self.assertFalse(compose_is_query(["exec", "redis", "command", "--help"]))

    def test_duplicate_volumes_and_unknown_env_fields_are_rejected(self):
        for content in ("REDIS_DATA_VOLUME=dev-infra-mysql84-data\n", "PATH=/unexpected\n"):
            self.instance.env_path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(InfraError):
                Instance(self.root)

    @unittest.skipUnless(os.name == "nt", "Native Windows transport")
    def test_transport_passes_preferences_without_passing_the_config_file(self):
        preferences = Settings(Path("not-forwarded.toml"), language="en", backup=False)
        payload = {"schema_version": JSON_SCHEMA_VERSION, "complete": True, "services": []}
        output = io.StringIO()
        with patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
        ) as run:
            self.assertEqual(cli.forward(["list", "--json"], preferences, json_stream=output), 0)
        self.assertEqual(json.loads(output.getvalue()), payload)
        self.assertTrue(run.call_args.kwargs["capture_output"])
        argv = run.call_args.args[0]
        self.assertIn("DEV_INFRA_TRANSPORT_LANGUAGE=en", argv)
        self.assertIn("DEV_INFRA_BACKUP=false", argv)
        self.assertNotIn(str(preferences.path), argv)

    def test_invalid_backend_output_returns_one_structured_transport_error(self):
        native_forward = cli.forward

        def windows_forward(*args, **kwargs):
            with patch.object(cli.os, "name", "nt"):
                return native_forward(*args, **kwargs)

        for stdout in (None, "", "{", "[]", "{}", '{"schema_version": true}', "{}\n{}"):
            with self.subTest(stdout=stdout):
                output, errors = io.StringIO(), io.StringIO()
                completed = subprocess.CompletedProcess([], 0, stdout, "fixture diagnostic\n")
                with (
                    patch.object(cli, "forward", side_effect=windows_forward),
                    patch("subprocess.run", return_value=completed),
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    code = cli.main(
                        ["--config", str(self.root / "missing-preferences.toml"), "list", "--json"]
                    )
                self.assertEqual(code, 1)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["schema_version"], JSON_SCHEMA_VERSION)
                self.assertEqual(payload["error"]["code"], "transport_failed")
                self.assertEqual(set(payload["error"]), {"code", "message", "details"})
                self.assertEqual(errors.getvalue(), "fixture diagnostic\n")


if __name__ == "__main__":
    unittest.main()
