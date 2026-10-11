import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "check_python", REPOSITORY / "scripts/check-python.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class RuntimeValidationTests(unittest.TestCase):
    def test_other_minor_versions_are_rejected(self):
        for version in ((3, 12), (3, 13), (3, 15)):
            with (
                self.subTest(version=version),
                patch.object(CHECK.sys, "version_info", version),
                self.assertRaisesRegex(RuntimeError, "3.14"),
            ):
                CHECK.check(sys.platform)

    def test_foreign_platform_is_rejected(self):
        platform = "linux" if sys.platform == "win32" else "win32"
        with self.assertRaisesRegex(RuntimeError, "原生"):
            CHECK.check(platform)

    def test_required_standard_library_modules_are_checked(self):
        with patch.dict(sys.modules, {"ssl": None}), self.assertRaises(ImportError):
            CHECK.check(sys.platform)


class NativeSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-python-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.binding = self.root / ".python"
        self.environment = {**os.environ, "TEST_APP_ROOT": str(self.root)}
        self.environment.pop("DEV_INFRA_PYTHON", None)
        if os.name == "nt":
            self.shell = shutil.which("pwsh")
            if self.shell is None:
                self.skipTest("PowerShell 7 unavailable")
            self.environment["TEST_HELPER"] = str(REPOSITORY / "scripts/python-runtime.ps1")
            self.argv = [
                self.shell,
                "-NoProfile",
                "-Command",
                (
                    "$ErrorActionPreference = 'Stop'; . $env:TEST_HELPER; "
                    "Resolve-DevInfraPython -AppRoot $env:TEST_APP_ROOT"
                ),
            ]
        else:
            self.shell = shutil.which("bash")
            if self.shell is None:
                self.skipTest("Bash unavailable")
            self.environment["TEST_HELPER"] = str(REPOSITORY / "scripts/python-runtime.sh")
            self.argv = [
                self.shell,
                "-c",
                'set -e; source "$TEST_HELPER"; dev_infra_resolve_python "$TEST_APP_ROOT"',
            ]
            binary = self.root / "bin"
            binary.mkdir()
            (binary / "python3.14").symlink_to(sys.executable)
            self.environment["PATH"] = str(binary) + os.pathsep + self.environment["PATH"]

    def invoke(self):
        return subprocess.run(
            self.argv,
            env=self.environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=30,
        )

    def assert_selected(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(result.stdout.strip()), Path(sys.executable).resolve())

    def test_path_is_used_when_no_binding_or_explicit_path_exists(self):
        self.assert_selected(self.invoke())

    def test_existing_external_binding_is_preserved(self):
        self.binding.write_text(str(Path(sys.executable).resolve()) + "\n", encoding="utf-8")
        original = self.binding.read_bytes()
        self.assert_selected(self.invoke())
        self.assertEqual(self.binding.read_bytes(), original)
        self.assertTrue(Path(sys.executable).is_file())

    def test_explicit_external_python_takes_priority_over_broken_binding(self):
        self.binding.write_text(str(self.root / "missing-python"), encoding="utf-8")
        self.environment["DEV_INFRA_PYTHON"] = sys.executable
        self.assert_selected(self.invoke())

    def test_invalid_explicit_path_does_not_fall_back_to_valid_binding(self):
        self.binding.write_text(sys.executable, encoding="utf-8")
        for path in ("", str(self.root / "missing-python")):
            with self.subTest(path=path):
                self.environment["DEV_INFRA_PYTHON"] = path
                self.assertNotEqual(self.invoke().returncode, 0)

    def test_broken_or_empty_binding_does_not_fall_back_to_path(self):
        for path in ("", str(self.root / "missing-python")):
            with self.subTest(path=path):
                self.binding.write_text(path, encoding="utf-8")
                self.assertNotEqual(self.invoke().returncode, 0)

    @unittest.skipUnless(os.name == "posix" and os.geteuid() == 0, "WSL root required")
    def test_uninstall_only_removes_entrypoint_and_preserves_external_python(self):
        binary = self.root / "bin"
        calls = self.root / "unlink-arguments"
        shim = binary / "rm"
        shim.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$TEST_CALLS"\n', encoding="utf-8")
        shim.chmod(0o755)
        result = subprocess.run(
            [self.shell, str(REPOSITORY / "scripts/uninstall.sh")],
            env={**self.environment, "TEST_CALLS": str(calls)},
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.read_text().splitlines(), ["-f", "/usr/local/bin/dev-infra"])
        self.assertTrue(Path(sys.executable).is_file())
