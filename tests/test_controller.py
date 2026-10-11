from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, cli, data, operations, planning, settings
from dev_infra.instance import Instance, read_env
from dev_infra.presentation import TEXT, Presentation
from tests.support import DIGEST, FakeDocker, FakeRegistry

REPOSITORY = Path(__file__).resolve().parents[1]


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (".env.example", "versions.env", "compose.yaml"):
            shutil.copyfile(REPOSITORY / name, self.root / name)
        shutil.copytree(REPOSITORY / "config", self.root / "config")
        (self.root / "config/mysql/my.cnf").chmod(0o644)
        self.preferences = self.root / "preferences.toml"
        self.instance = Instance(self.root)
        self.docker = FakeDocker(self.instance)
        self.addCleanup(patch.stopall)
        patch.object(cli, "ROOT", self.root).start()
        patch.object(cli, "forward", return_value=None).start()
        patch.object(cli, "Docker", return_value=self.docker).start()
        patch.object(cli, "Registry", FakeRegistry).start()
        patch.object(Instance, "lock", side_effect=contextlib.nullcontext).start()

    def invoke(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = cli.main(["--config", str(self.preferences), *args])
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_queries_do_not_initialize_configuration_or_state(self):
        for args in (
            ("list",),
            ("show", "mysql"),
            ("check",),
            ("check", "--updates"),
            ("upgrade", "mysql", "--dry-run"),
            ("data", "list"),
            ("data", "prune", "--dry-run"),
            ("config", "check"),
            ("config", "show", "--versions"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args)[0], 0)
                self.assertFalse(self.instance.env_path.exists())
                self.assertFalse(self.instance.state.exists())
                self.assertFalse(self.preferences.exists())
        self.assertFalse(any(c[0] in ("pull", "up", "rm") for c in self.docker.calls))

    def test_invalid_arguments_have_no_docker_or_config_side_effects(self):
        for args in (
            ("start", "unknown"),
            ("data", "reset", "redis", "--yes", "unexpected"),
            ("data", "backup", "redis"),
            ("data", "backup", "mysql", "--dry-run"),
            ("upgrade", "all", "--to", "18.6"),
            ("upgrade", "redis", "--no-backups"),
            ("show", "mysql", "--open"),
            ("self", "status", "--source", "."),
        ):
            with self.subTest(args=args):
                self.docker.calls.clear()
                self.assertNotEqual(self.invoke(*args)[0], 0)
                self.assertFalse(self.docker.calls)
                self.assertFalse(self.instance.env_path.exists())

    def test_help_uses_preferences_language(self):
        for language, word in (("zh", "用法"), ("en", "usage")):
            self.preferences.write_text(f'language = "{language}"\n', encoding="utf-8")
            code, output, _ = self.invoke("help", "upgrade")
            self.assertEqual(code, 0)
            self.assertIn(word, output)
            self.assertIn("--to", output)

    def test_cli_rejects_other_python_minor_versions_before_docker_access(self):
        for version in ((3, 11), (3, 12), (3, 13), (3, 15)):
            with self.subTest(version=version), patch.object(cli.sys, "version_info", version):
                code, _, errors = self.invoke("list")
            self.assertEqual(code, 1)
            self.assertIn("Python 3.14", errors)
            self.assertFalse(self.docker.calls)
            self.assertFalse(self.instance.env_path.exists())

    def test_json_identifiers_do_not_change_with_language(self):
        values = []
        for language in ("zh", "en"):
            self.preferences.write_text(f'language = "{language}"\n', encoding="utf-8")
            code, output, _ = self.invoke("list", "--json")
            self.assertEqual(code, 0)
            values.append(json.loads(output))
        self.assertEqual(values[0], values[1])

    def test_default_is_list_and_connection_passwords_are_masked(self):
        self.assertEqual(self.invoke()[0], 0)
        _, output, _ = self.invoke("show", "mysql", "--json")
        self.assertNotIn("dev123456", output)
        self.assertNotIn("root123456", output)
        _, output, _ = self.invoke("show", "mysql", "--secrets", "--json")
        self.assertIn("dev123456", output)

    def test_mysql_backup_returns_success_and_contains_valid_gzip(self):
        code, output, errors = self.invoke("data", "backup", "mysql", "--json")
        self.assertEqual(code, 0, errors)
        payload = json.loads(output)
        path = Path(payload["backups"][0]["path"])
        self.assertIn("isolated SQL", gzip.decompress(path.read_bytes()).decode())

    def test_failed_dump_does_not_publish_a_backup(self):
        with patch.dict(os.environ, {"TEST_DUMP_EXIT": "1"}), self.assertRaises(InfraError):
            data.backup(self.docker, ["mysql"])
        self.assertEqual(list((self.root / "backup").iterdir()), [])

    def test_upgrade_uses_real_backup_then_pins_fixed_version_and_digest(self):
        code, output, errors = self.invoke("upgrade", "mysql", "--json")
        self.assertEqual(code, 0, errors)
        payload = json.loads(output)
        self.assertEqual(payload["state"], "complete")
        self.assertTrue(list((self.root / "backup").glob("*.sql.gz")))
        self.assertEqual(
            read_env(self.instance.overrides_path)["MYSQL_VERSION"], "8.4.11@" + DIGEST
        )
        self.assertTrue(any(c[0] == "pull" for c in self.docker.calls))

    def test_no_backup_is_explicit_and_s3_client_is_included(self):
        code, output, errors = self.invoke("upgrade", "s3", "--no-backup", "--json")
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(json.loads(output)["images"]), 2)
        self.assertIn("RUSTFS_RC_VERSION", read_env(self.instance.overrides_path))
        self.assertFalse((self.root / "backup").exists())

    def test_pinned_digest_runtime_image_keeps_compatible_scope(self):
        self.docker.entries["postgres"]["Config"]["Image"] = "postgres:18.5@" + DIGEST
        code, output, errors = self.invoke("upgrade", "postgres", "--dry-run", "--json")
        self.assertEqual(code, 0, errors)
        self.assertFalse(json.loads(output)["blocked"])

    def test_target_branch_does_not_require_a_registry_alias_tag(self):
        with patch.object(FakeRegistry, "exact", side_effect=AssertionError("branch is not a tag")):
            code, output, errors = self.invoke(
                "upgrade", "kafka", "--to", "4.3", "--dry-run", "--json"
            )
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["images"][0]["version"], "4.3.1@" + DIGEST)

    def test_current_images_do_not_restart_services(self):
        self.docker.current = True
        code, output, _ = self.invoke("upgrade", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["state"], "unchanged")
        self.assertFalse(any(c[0] == "pull" for c in self.docker.calls))
        self.assertFalse(self.instance.state.exists())

    def test_stopped_database_blocks_default_backup_upgrade(self):
        self.docker.entries["mysql"]["State"]["Status"] = "exited"
        self.assertEqual(self.invoke("upgrade", "mysql")[0], 1)
        self.assertFalse(any(c[0] == "pull" for c in self.docker.calls))
        self.assertFalse(self.instance.overrides_path.exists())

    def test_start_does_not_reuse_incompatible_existing_volume(self):
        self.instance.values["POSTGRES_VERSION"] = "19.1"
        self.assertEqual(self.invoke("start", "postgres")[0], 1)
        self.assertFalse(any(c[0] == "up" for c in self.docker.calls))
        self.assertFalse(self.instance.env_path.exists())

    def test_upgrade_preview_blocks_incompatible_stopped_database_volume(self):
        self.docker.entries.pop("postgres")
        volume = self.instance.values["POSTGRES_DATA_VOLUME"]
        self.docker.volume_metadata[volume]["Labels"]["io.dev-infra.scope"] = "17"
        for extra in (("--dry-run",), ()):
            code, output, _ = self.invoke("upgrade", "postgres", "--no-backup", "--json", *extra)
            self.assertEqual(code, 1)
            self.assertTrue(json.loads(output)["blocked"])
            self.assertFalse(self.instance.env_path.exists())
            self.assertFalse(self.instance.state.exists())
        self.assertFalse(any(c[0] in ("pull", "up") for c in self.docker.calls))

    def test_migration_and_downgrade_are_blocked_before_mutations(self):
        self.docker.current = True
        for version, reason in (("19.1", "migration_required"), ("18.5", "downgrade_blocked")):
            with self.subTest(version=version):
                code, output, _ = self.invoke("upgrade", "postgres", "--to", version, "--json")
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output)["images"][0]["reason"], reason)
                self.assertFalse(self.instance.state.exists())
                self.assertFalse(self.instance.env_path.exists())

    def test_registry_failure_preserves_other_results_and_blocks_execution(self):
        with patch.object(FakeRegistry, "failure", "redis"):
            code, output, _ = self.invoke("upgrade", "--json")
        payload = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual(len(payload["images"]), 7)
        self.assertFalse(payload["complete"])
        self.assertFalse(self.instance.overrides_path.exists())

    def test_pull_failure_does_not_change_version_declarations(self):
        self.docker.fail_pull = True
        self.assertEqual(self.invoke("upgrade", "redis", "--no-backup")[0], 1)
        self.assertFalse(self.instance.overrides_path.exists())
        self.assertFalse(any(c[0] == "up" for c in self.docker.calls))
        self.assertEqual(self.instance.read_state("last-upgrade.json")["state"], "error")

    def test_health_failure_retains_target_and_journal_for_retry(self):
        self.docker.fail_up = True
        self.assertEqual(self.invoke("upgrade", "redis", "--no-backup")[0], 1)
        self.assertTrue(self.instance.overrides_path.exists())
        self.assertEqual(self.instance.read_state("last-upgrade.json")["state"], "error")

    def test_changed_configuration_invalidates_upgrade_plan(self):
        proposal = planning.plan(self.docker, FakeRegistry(), ["redis"], to=None, backup=False)
        self.instance.env_path.write_text("REDIS_PORT=26380\n", encoding="utf-8")
        with self.assertRaisesRegex(InfraError, "plan_changed"):
            operations.upgrade(self.docker, settings.Settings(self.preferences), proposal)
        self.assertFalse(self.instance.overrides_path.exists())

    def test_volume_prune_keeps_active_and_unrelated_volumes(self):
        old = "dev-infra-postgres17-data"
        foreign = "unrelated-data"
        for name in (old, foreign):
            self.docker.volume_metadata[name] = {
                "Name": name,
                "Labels": {},
                "Mountpoint": "/isolated/" + name,
            }
        code, output, errors = self.invoke("data", "prune", "--yes", "--json")
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["removed"], [old])
        self.assertIn(foreign, self.docker.volume_metadata)
        self.assertEqual(len(self.docker.volume_metadata), 7)

    def test_reset_requires_confirmation_before_stop_or_delete(self):
        code, _, _ = self.invoke("data", "reset", "redis")
        self.assertEqual(code, 1)
        self.assertFalse(any(c[0] in ("stop", "rm") for c in self.docker.calls))

    def test_config_edit_can_repair_invalid_toml(self):
        self.preferences.write_text("not toml", encoding="utf-8")
        with patch.object(
            settings,
            "edit",
            side_effect=lambda path, *_: path.write_text('language = "en"\n', encoding="utf-8"),
        ):
            self.assertEqual(self.invoke("config", "edit")[0], 0)
        self.assertEqual(settings.load(self.preferences).language, "en")


class SettingsTests(unittest.TestCase):
    def test_catalog_has_both_languages_for_all_messages(self):
        self.assertTrue(all(len(values) == 2 and all(values) for values in TEXT.values()))
        for language in ("zh", "en"):
            parser, _ = cli.catalog(Presentation(language))
            self.assertIn("upgrade", parser.format_help())

    def test_invalid_fields_and_types_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            for content in (
                'language="fr"',
                'editor="vi"',
                '[operation]\nbackup="false"',
                "[operation]\nwait_timeout=true",
                "[wsl]\ndistro=0",
                "unknown=true",
            ):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(InfraError):
                    settings.load(path)

    def test_environment_config_is_parsed_as_data_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "values.env"
            path.write_text("VALUE=$(touch never-execute)\n", encoding="utf-8")
            self.assertEqual(read_env(path)["VALUE"], "$(touch never-execute)")
            self.assertFalse((root / "never-execute").exists())

    def test_configured_editor_is_an_argv_array(self):
        value = settings.Settings(Path("config.toml"), editor=("code", "--wait"))
        self.assertEqual(settings.editor(value), ["code", "--wait"])

    @unittest.skipUnless(os.name == "nt", "Native Windows editor argv")
    def test_windows_editor_environment_handles_quoted_paths(self):
        value = settings.Settings(Path("config.toml"))
        with patch.dict(os.environ, {"VISUAL": '"C:\\Program Files\\Editor\\edit.exe" --wait'}):
            self.assertEqual(
                settings.editor(value), [r"C:\Program Files\Editor\edit.exe", "--wait"]
            )

    @unittest.skipUnless(os.name == "nt", "Native Windows preferences")
    def test_windows_preferences_do_not_depend_on_package_appdata_redirection(self):
        with patch.dict(os.environ, {"APPDATA": r"C:\isolated-package\Roaming"}):
            self.assertEqual(settings.default_path(), Path.home() / ".config/dev-infra/config.toml")


if __name__ == "__main__":
    unittest.main()
