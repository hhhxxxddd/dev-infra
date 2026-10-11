import argparse
import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import cli
from dev_infra.presentation import Presentation


class CommandHelpTests(unittest.TestCase):
    def test_grouped_help_lists_every_actual_parser_once_in_both_languages(self):
        for language in ("zh", "en"):
            with self.subTest(language=language):
                presentation = Presentation(language)
                root, parsers = cli.catalog(presentation)
                commands = next(
                    action
                    for action in root._actions
                    if isinstance(action, argparse._SubParsersAction)
                )
                output = root.format_help()
                self.assertEqual(set(commands.choices), set(parsers))
                self.assertEqual(set(parsers), {item.name for item in cli.COMMANDS})
                # argparse must not add a second command table alongside the grouped one.
                self.assertFalse(commands._choices_actions)
                for name in commands.choices:
                    self.assertEqual(
                        len(re.findall(rf"^  {name}\s{{2,}}", output, re.MULTILINE)),
                        1,
                        name,
                    )
                groups = tuple(dict.fromkeys(item.group for item in cli.COMMANDS))
                self.assertEqual(
                    groups, ("common_commands", "advanced_commands", "auxiliary_commands")
                )
                for index, group in enumerate(groups):
                    start = output.index(presentation.t(group) + ":\n")
                    end = (
                        output.index(presentation.t(groups[index + 1]) + ":\n")
                        if index + 1 < len(groups)
                        else output.index(presentation.t("help_usage"))
                    )
                    section = output[start:end]
                    expected = [item.name for item in cli.COMMANDS if item.group == group]
                    self.assertEqual(
                        re.findall(r"^  ([a-z]+)\s{2,}", section, re.MULTILINE), expected
                    )
                self.assertIn("self upgrade", output)
                self.assertIn(
                    "升级工具自身" if language == "zh" else "upgrades the tool itself", output
                )
                self.assertIn("升级中间件" if language == "zh" else "Upgrade middleware", output)
                self.assertIn("config edit", output)
                self.assertIn(presentation.t("data_summary"), output)
                self.assertIn(
                    "\n\n" + presentation.t("help_usage") + "\n" + presentation.t("help_examples"),
                    output,
                )

    def invoke(self, path, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = cli.main(["--config", str(path), *arguments])
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), errors.getvalue()

    def test_help_entrypoints_are_equivalent_local_and_read_only(self):
        with (
            tempfile.TemporaryDirectory(prefix="dev-infra-help-") as temporary,
            patch.object(cli, "Docker", side_effect=AssertionError("help accessed Docker")),
            patch.object(cli, "Instance", side_effect=AssertionError("help accessed instance")),
            patch.object(cli, "forward", side_effect=AssertionError("help forwarded to WSL")),
            patch.object(cli, "Registry", side_effect=AssertionError("help accessed registry")),
            patch.dict(os.environ),
        ):
            os.environ.pop("DEV_INFRA_TRANSPORT_LANGUAGE", None)
            root = Path(temporary)
            preferences = root / "preferences.toml"
            for language in ("zh", "en"):
                with self.subTest(language=language):
                    if language == "en":
                        preferences.write_text('language = "en"\n', encoding="utf-8")
                    before = {path.name: path.read_bytes() for path in root.iterdir()}
                    forms = [
                        self.invoke(preferences, *args) for args in ((), ("help",), ("--help",))
                    ]
                    self.assertEqual(forms[0], forms[1])
                    self.assertEqual(forms[0], forms[2])
                    self.assertEqual(forms[0][0], 0)
                    self.assertFalse(forms[0][2])
                    self.assertIn(Presentation(language).t("common_commands"), forms[0][1])
                    self.assertEqual(
                        {path.name: path.read_bytes() for path in root.iterdir()}, before
                    )
                    for topic in (item.name for item in cli.COMMANDS if item.name != "help"):
                        explicit = self.invoke(preferences, "help", topic)
                        option = self.invoke(preferences, topic, "--help")
                        self.assertEqual(explicit, option, topic)
                        self.assertEqual(explicit[0], 0, topic)
                    self.assertEqual(
                        {path.name: path.read_bytes() for path in root.iterdir()}, before
                    )

    def test_subcommand_help_and_parsing_keep_existing_parameters(self):
        root, parsers = cli.catalog(Presentation("zh"))
        for name, expected in {
            "show": ("--json", "--secrets", "--open"),
            "logs": ("--follow", "--tail"),
            "check": ("--updates", "--to", "--backup", "--no-backup"),
            "upgrade": ("--to", "--backup", "--no-backup"),
            "config": ("--instance", "--versions", "--json"),
            "data": ("--yes", "--json"),
            "self": ("--source", "--json"),
        }.items():
            with self.subTest(command=name):
                output = parsers[name].format_help()
                for option in expected:
                    self.assertIn(option, output)
        for name, choices, default in (
            ("config", ("show", "edit", "check"), "show"),
            ("data", ("list", "prune", "backup", "reset"), "list"),
            ("self", ("status", "update", "upgrade"), "status"),
        ):
            action = next(item for item in parsers[name]._actions if item.dest == "action")
            self.assertEqual(action.choices, choices)
            self.assertEqual(root.parse_args([name]).action, default)
            for choice in choices:
                self.assertIn(choice, parsers[name].format_help())
        parsed = root.parse_args(["upgrade", "mysql", "--to", "8.4.11", "--no-backup"])
        self.assertEqual((parsed.services, parsed.to, parsed.backup), (["mysql"], "8.4.11", False))
        parsed = root.parse_args(["data", "reset", "redis", "--yes"])
        self.assertEqual((parsed.action, parsed.services, parsed.yes), ("reset", ["redis"], True))
        parsed = root.parse_args(["compose", "ps", "--all"])
        self.assertEqual(parsed.arguments, ["ps", "--all"])


if __name__ == "__main__":
    unittest.main()
