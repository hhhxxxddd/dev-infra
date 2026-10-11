import os
import re
import shutil
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
        candidates = []
        if os.name == "nt":
            if git := shutil.which("git"):
                candidates.append(Path(git).resolve().parent.parent / "bin/bash.exe")
            if program_files := os.environ.get("ProgramFiles"):
                candidates.append(Path(program_files) / "Git/bin/bash.exe")
        if configured := shutil.which("bash"):
            candidates.append(Path(configured))
        bash = None
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                probe = subprocess.run(
                    [str(candidate), "--version"], capture_output=True, check=False, timeout=10
                )
            except OSError, subprocess.TimeoutExpired:
                continue
            if probe.returncode == 0 and b"GNU bash" in probe.stdout:
                bash = str(candidate)
                break
        if bash is None:
            self.skipTest("Working Bash unavailable")
        for language in ("", ".en"):
            path = REPOSITORY / f"docs/upgrades{language}.md"
            for snippet in re.findall(
                r"```bash\n(.*?)```", path.read_text(encoding="utf-8"), re.DOTALL
            ):
                result = subprocess.run(
                    [bash, "-n"], input=snippet.encode("utf-8"), capture_output=True, check=False
                )
                self.assertEqual(
                    result.returncode, 0, result.stderr.decode("utf-8", errors="replace")
                )


if __name__ == "__main__":
    unittest.main()
