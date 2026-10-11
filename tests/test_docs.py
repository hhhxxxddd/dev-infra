import re
import subprocess
import tomllib
import unittest
from pathlib import Path

from dev_infra.cli import catalog
from dev_infra.presentation import Presentation
from dev_infra.settings import TEMPLATE

REPOSITORY = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_and_toml_examples(self):
        for path in [*REPOSITORY.glob("README*.md"), *(REPOSITORY / "docs").glob("*.md")]:
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue(
                        (path.parent / target.split("#")[0]).exists(), f"{path}: {target}"
                    )
            for snippet in re.findall(r"```toml\n(.*?)```", text, re.DOTALL):
                tomllib.loads(snippet)
        tomllib.loads(TEMPLATE)

    def test_bilingual_readmes_have_the_same_commands(self):
        def commands(path):
            return [
                line.split("#")[0].rstrip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("dev-infra")
            ]

        self.assertEqual(commands(REPOSITORY / "README.md"), commands(REPOSITORY / "README.en.md"))

    def test_documented_cli_commands_exist(self):
        _, parsers = catalog(Presentation("zh"))
        for path in [*REPOSITORY.glob("README*.md"), *(REPOSITORY / "docs").glob("*.md")]:
            for command in re.findall(
                r"^dev-infra ([a-z]+)", path.read_text(encoding="utf-8"), re.MULTILINE
            ):
                self.assertIn(command, parsers, f"{path}: {command}")

    def test_migration_snippets_have_valid_bash_syntax(self):
        if not __import__("shutil").which("bash"):
            self.skipTest("Native Bash unavailable")
        for language in ("", ".en"):
            path = REPOSITORY / f"docs/upgrades{language}.md"
            for snippet in re.findall(
                r"```bash\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
            ):
                result = subprocess.run(
                    ["bash", "-n"], input=snippet.encode("utf-8"), capture_output=True, check=False
                )
                self.assertEqual(
                    result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
                )


if __name__ == "__main__":
    unittest.main()
