from __future__ import annotations

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, __version__, cli, operations, settings
from dev_infra.docker import Docker
from dev_infra.instance import Instance
from dev_infra.presentation import Presentation


@unittest.skipUnless(shutil.which("git"), "Git is required")
class SourceUpgradeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.remote = self.root / "upstream"
        self.checkout = self.root / "checkout"
        self.real_run = subprocess.run
        self.git("init", "--initial-branch=main", str(self.remote))
        self.git("-C", str(self.remote), "config", "user.email", "test@example.invalid")
        self.git("-C", str(self.remote), "config", "user.name", "Test")
        (self.remote / "scripts").mkdir()
        (self.remote / "scripts/install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        self.commit("first")
        self.git("clone", str(self.remote), str(self.checkout))
        self.git(
            "-C",
            str(self.checkout),
            "remote",
            "set-url",
            "origin",
            "https://github.com/hhhxxxddd/dev-infra.git",
        )
        self.calls = []

    def git(self, *arguments):
        return self.real_run(["git", *arguments], check=True, capture_output=True, text=True)

    def commit(self, text):
        (self.remote / "version.txt").write_text(text, encoding="utf-8")
        self.git("-C", str(self.remote), "add", ".")
        self.git("-C", str(self.remote), "commit", "-m", text)

    def run_git(self, command, **kwargs):
        self.calls.append(command)
        if "fetch" in command:
            command = [str(self.remote) if token == "origin" else token for token in command]
        return self.real_run(command, **kwargs)

    def test_fast_forward_fetches_new_code_without_running_installers(self):
        self.commit("second")
        with patch.object(operations.subprocess, "run", side_effect=self.run_git):
            operations.refresh_checkout(self.checkout)
        self.assertEqual((self.checkout / "version.txt").read_text(), "second")
        self.assertTrue(any("fetch" in command and "origin" in command for command in self.calls))
        self.assertTrue(
            any("merge" in command and "--ff-only" in command for command in self.calls)
        )

    def test_local_changes_rejected_before_fetch(self):
        (self.checkout / "version.txt").write_text("local work", encoding="utf-8")
        with (
            patch.object(operations.subprocess, "run", side_effect=self.run_git),
            self.assertRaisesRegex(InfraError, "source_dirty"),
        ):
            operations.refresh_checkout(self.checkout)
        self.assertFalse(any("fetch" in command for command in self.calls))
        self.assertEqual((self.checkout / "version.txt").read_text(), "local work")

    def test_divergence_cannot_create_merge_commit(self):
        self.commit("upstream change")
        self.git("-C", str(self.checkout), "config", "user.email", "test@example.invalid")
        self.git("-C", str(self.checkout), "config", "user.name", "Test")
        (self.checkout / "local.txt").write_text("local commit", encoding="utf-8")
        self.git("-C", str(self.checkout), "add", ".")
        self.git("-C", str(self.checkout), "commit", "-m", "local commit")
        original = self.git("-C", str(self.checkout), "rev-parse", "HEAD").stdout
        with (
            patch.object(operations.subprocess, "run", side_effect=self.run_git),
            self.assertRaisesRegex(InfraError, "source_update_failed"),
        ):
            operations.refresh_checkout(self.checkout)
        self.assertEqual(self.git("-C", str(self.checkout), "rev-parse", "HEAD").stdout, original)


class SelfUpgradeCliTests(unittest.TestCase):
    def test_docker_timeout_hides_command_parameters(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "dev_infra.docker.subprocess.run",
                side_effect=subprocess.TimeoutExpired(["docker", "secret-token"], 30),
            ),
        ):
            root = Path(temporary)
            shutil.copyfile(
                Path(__file__).resolve().parents[1] / "versions.env", root / "versions.env"
            )
            shutil.copyfile(
                Path(__file__).resolve().parents[1] / ".env.example", root / ".env.example"
            )
            with self.assertRaisesRegex(InfraError, "command_timeout") as result:
                Docker(Instance(root)).run("info")
            self.assertNotIn("secret-token", str(result.exception))

    def test_recovery_presentation_has_translated_actions_and_backup_paths(self):
        payload = {
            "checks": [{"check": "upgrade_recovery", "state": "error"}],
            "recovery": {
                "needs_attention": True,
                "stage": "recreate",
                "journal": "/isolated/last-upgrade.json",
                "error": {"code": "command_timeout", "message": "command_timeout"},
                "completed_steps": ["backup", "pull"],
                "backups": [
                    {"service": "mysql", "state": "complete", "path": "/isolated/mysql.sql.gz"}
                ],
                "services": [{"service": "mysql", "state": "error", "target": "mysql:8.4"}],
                "recommendations": [
                    {
                        "action": "retry_upgrade",
                        "argv": ["dev-infra", "upgrade", "mysql", "--to", "8.4.11"],
                    }
                ],
            },
        }
        for language in ("zh", "en"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                Presentation(language).output(payload, False)
            self.assertIn("/isolated/mysql.sql.gz", output.getvalue())
            self.assertIn("dev-infra upgrade mysql --to 8.4.11", output.getvalue())
            self.assertNotIn("retry_upgrade", output.getvalue())
            self.assertNotIn("command_timeout", output.getvalue())

    def test_version_aliases_and_upgrade_do_not_forward_to_middleware(self):
        with tempfile.TemporaryDirectory() as temporary:
            preferences = Path(temporary) / "config.toml"
            for flag in ("-v", "--version"):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
                    cli.main(["--config", str(preferences), flag])
                self.assertEqual(result.exception.code, 0)
                self.assertIn(__version__, output.getvalue())
            with (
                patch.object(cli, "forward", side_effect=AssertionError("middleware transport")),
                patch.object(
                    operations, "self_command", return_value={"state": "complete"}
                ) as upgrade,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(
                    cli.main(
                        ["--config", str(preferences), "self", "upgrade", "--source", temporary]
                    ),
                    0,
                )
                self.assertEqual(upgrade.call_args.args[:2], ("upgrade", temporary))

    def test_dirty_source_never_executes_installer(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            with (
                patch.object(operations, "verify_source", return_value={"channel": "git"}),
                patch.object(
                    operations, "refresh_checkout", side_effect=InfraError("source_dirty")
                ),
                patch.object(operations.subprocess, "run", side_effect=AssertionError("installer")),
                patch("os.geteuid", return_value=0, create=True),
                self.assertRaisesRegex(InfraError, "source_dirty"),
            ):
                operations.self_command(
                    "upgrade", str(checkout), settings.Settings(checkout / "config.toml")
                )
