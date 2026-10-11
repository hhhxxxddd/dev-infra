from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, __version__, operations, package_smoke, release, settings, source

REPOSITORY = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("git"), "Git is required for release provenance")
class ReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dev-infra-release-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.checkout = self.root / "checkout"
        self.checkout.mkdir()
        for name, path in source.payload_paths(REPOSITORY).items():
            target = self.checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("remote", "add", "origin", "https://github.com/hhhxxxddd/dev-infra.git")
        self.git("add", ".")
        self.git("commit", "-m", "release fixture")
        self.git("tag", "v" + __version__)
        self.output = self.root / "artifacts"

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.checkout), *arguments],
            capture_output=True,
            text=True,
            check=True,
        )

    def package(self):
        built = release.build(self.checkout, self.output)
        target = self.root / "package"
        source.extract_package(Path(built["archive"]), target, built["sha256"])
        return target, built

    def test_complete_payload_reproducibility_and_receipt(self):
        first = release.build(self.checkout, self.output)
        content = Path(first["archive"]).read_bytes()
        second = release.build(self.checkout, self.root / "again")
        self.assertEqual(content, Path(second["archive"]).read_bytes())
        with zipfile.ZipFile(first["archive"]) as archive:
            self.assertTrue(set(source.REQUIRED).issubset(archive.namelist()))
            self.assertTrue(
                all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
            )
            receipt = json.loads(archive.read(source.RECEIPT))
            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(receipt["repository"], source.UPSTREAM)
            self.assertEqual(
                receipt["provenance"]["commit"], self.git("rev-parse", "HEAD").stdout.strip()
            )
            self.assertFalse(receipt["provenance"]["dirty"])
            for name, expected in receipt["files"].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), expected)
        manifest = json.loads((self.output / "dev-infra.json").read_text())
        self.assertEqual(manifest["hash"], first["sha256"])
        self.assertNotIn("python", " ".join(manifest["depends"]))

    def test_dirty_candidates_exclude_native_state_and_caches(self):
        for name in (
            ".python",
            ".source",
            ".env",
            "versions.local.env",
            ".state/secret.json",
            "backup/data.sql",
            "host/bin/python",
            "src/dev_infra/__pycache__/cached.pyc",
            "docs/settings.local.md",
        ):
            target = self.checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("machine-private", encoding="utf-8")
        built = release.build(self.checkout, self.output)
        self.assertTrue(built["provenance"]["dirty"])
        with zipfile.ZipFile(built["archive"]) as archive:
            self.assertFalse(
                any(b"machine-private" in archive.read(name) for name in archive.namelist())
            )
            self.assertTrue(
                all(
                    source.allowed_name(name) or name == source.RECEIPT
                    for name in archive.namelist()
                )
            )

    def test_line_endings_do_not_change_dirty_candidate_bytes(self):
        readme = self.checkout / "README.md"
        readme.write_bytes(readme.read_bytes().replace(b"\r\n", b"\n") + b"\ncandidate\n")
        first = release.build(self.checkout, self.output)
        content = Path(first["archive"]).read_bytes()
        for path in source.payload_paths(self.checkout).values():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        second = release.build(self.checkout, self.root / "crlf")
        self.assertEqual(content, Path(second["archive"]).read_bytes())

    def test_document_binary_assets_are_preserved(self):
        content = b"\x89PNG\r\n\x1a\nexample\r\n"
        (self.checkout / "docs/example.png").write_bytes(content)
        built = release.build(self.checkout, self.output)
        with zipfile.ZipFile(built["archive"]) as archive:
            self.assertEqual(archive.read("docs/example.png"), content)

    def test_official_build_requires_clean_matching_tag_and_notes(self):
        release.build(self.checkout, self.output, "v" + __version__, official=True)
        with self.assertRaises(ValueError):
            release.build(self.checkout, self.output, official=True)
        (self.checkout / "README.md").write_text("local edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "clean"):
            release.build(self.checkout, self.output, "v" + __version__, official=True)
        self.git("add", ".")
        self.git("commit", "-m", "ahead")
        with self.assertRaisesRegex(ValueError, "matching"):
            release.build(self.checkout, self.output, "v" + __version__, official=True)
        (self.checkout / "docs/releases" / f"v{__version__}.md").unlink()
        self.git("add", ".")
        self.git("commit", "-m", "missing notes")
        self.git("tag", "-f", "v" + __version__)
        with self.assertRaises(FileNotFoundError):
            release.build(self.checkout, self.output, "v" + __version__, official=True)

    def test_mismatched_version_or_tag_rejected(self):
        with self.assertRaisesRegex(ValueError, "match"):
            release.build(self.checkout, self.output, "v999.0.0")
        metadata = self.checkout / "pyproject.toml"
        metadata.write_text(
            metadata.read_text().replace(f'version = "{__version__}"', 'version = "999.0.0"')
        )
        with self.assertRaises(InfraError):
            release.build(self.checkout, self.output)

    def test_receipt_rejects_tampering_missing_and_extra_code(self):
        package, _ = self.package()
        self.assertEqual(source.verify_source(package)["channel"], "release")
        target = package / "scripts/install.sh"
        original = target.read_bytes()
        target.write_bytes(original + b"\necho changed\n")
        with self.assertRaises(InfraError):
            source.verify_package(package)
        target.write_bytes(original)
        injected = package / "src/dev_infra/injected.py"
        injected.write_text("injected", encoding="utf-8")
        with self.assertRaises(InfraError):
            source.verify_package(package)
        injected.unlink()
        target.unlink()
        with self.assertRaises(InfraError):
            source.verify_package(package)

    def test_package_receipt_rejects_repository_version_and_schema_forgery(self):
        package, _ = self.package()
        target = package / source.RECEIPT
        original = json.loads(target.read_text())
        for key, value in (
            ("repository", "other/repository"),
            ("version", "999.0.0"),
            ("schema_version", True),
            ("schema_version", 1.0),
            ("provenance", {"commit": "not-a-commit", "dirty": False}),
            ("provenance", {"commit": "0" * 40, "dirty": "false"}),
        ):
            with self.subTest(key=key):
                target.write_text(json.dumps({**original, key: value}))
                with self.assertRaises(InfraError):
                    source.verify_package(package)

    def test_archive_unsafe_members_are_rejected_before_writing(self):
        for name, mode in (
            ("../escape", stat.S_IFREG),
            ("/absolute", stat.S_IFREG),
            ("C:/drive", stat.S_IFREG),
            ("scripts/NUL", stat.S_IFREG),
            ("scripts/link", stat.S_IFLNK),
        ):
            with self.subTest(name=name):
                archive = self.root / "unsafe.zip"
                with zipfile.ZipFile(archive, "w") as package:
                    item = zipfile.ZipInfo(name)
                    item.external_attr = (mode | 0o644) << 16
                    package.writestr(item, "content")
                destination = self.root / "unsafe-output"
                with self.assertRaises(InfraError):
                    source.extract_package(archive, destination)
                self.assertFalse(destination.exists())
        self.assertFalse((self.root / "escape").exists())

        with zipfile.ZipFile(self.root / "aliases.zip", "w") as package:
            package.writestr("docs/alias.md", "first")
            package.writestr("docs/Alias.md", "second")
        with self.assertRaises(InfraError):
            source.extract_package(self.root / "aliases.zip", self.root / "aliases")
        self.assertFalse((self.root / "aliases").exists())

    def test_symlink_payload_and_destination_are_rejected(self):
        link = self.checkout / "scripts/link.py"
        try:
            link.symlink_to(self.checkout / "scripts/dev-infra.py")
        except OSError:
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(InfraError):
            release.build(self.checkout, self.output)
        link.unlink()
        built = release.build(self.checkout, self.output)
        external = self.root / "external"
        external.mkdir()
        destination = self.root / "linked-output"
        destination.symlink_to(external, target_is_directory=True)
        with self.assertRaises(InfraError):
            source.extract_package(Path(built["archive"]), destination)
        self.assertEqual(list(external.iterdir()), [])

    def test_official_download_checks_checksum_and_receipt_version(self):
        built = release.build(self.checkout, self.output)
        requests = []

        def read(url, limit):
            requests.append(url)
            if url.endswith("/latest"):
                return json.dumps(
                    {
                        "tag_name": "v" + __version__,
                        "assets": [{"browser_download_url": "https://untrusted.invalid/package"}],
                    }
                ).encode()
            if url.endswith("SHA256SUMS"):
                return (self.output / "SHA256SUMS").read_bytes()
            return Path(built["archive"]).read_bytes()

        with patch.object(source, "_read_url", side_effect=read):
            downloaded = source.download_release(self.root / "download")
        self.assertEqual(source.verify_package(downloaded)["version"], __version__)
        self.assertTrue(
            all(
                url.startswith(
                    (
                        f"https://api.github.com/repos/{source.UPSTREAM}/",
                        f"https://github.com/{source.UPSTREAM}/",
                    )
                )
                for url in requests
            )
        )
        with (
            patch.object(
                source,
                "_read_url",
                side_effect=lambda url, limit: (
                    json.dumps({"tag_name": "v" + __version__}).encode()
                    if url.endswith("/latest")
                    else (b"0" * 64 + f"  dev-infra-{__version__}.zip\n".encode())
                    if url.endswith("SHA256SUMS")
                    else Path(built["archive"]).read_bytes()
                ),
            ),
            self.assertRaises(InfraError),
        ):
            source.download_release(self.root / "bad-download")

    def test_native_entrypoint_package_smoke_is_offline(self):
        built = release.build(self.checkout, self.output)
        result = package_smoke.smoke(Path(built["archive"]), self.root / "smoke")
        self.assertEqual(result["state"], "complete")
        self.assertTrue(result["native_entrypoint"])
        self.assertEqual(result["version"], __version__)
        (self.output / "SHA256SUMS").write_text(
            "0" * 64 + f"  dev-infra-{__version__}.zip\n", encoding="ascii"
        )
        with (
            patch.object(package_smoke.subprocess, "run", side_effect=AssertionError("entrypoint")),
            self.assertRaisesRegex(ValueError, "checksum"),
        ):
            package_smoke.smoke(Path(built["archive"]), self.root / "unverified-smoke")

    def test_release_notes_links_pin_commit_and_missing_notes_fail(self):
        commit = self.git("rev-parse", "HEAD").stdout.strip()
        notes = release.release_notes(self.checkout, "v" + __version__, commit)
        self.assertIn(f"https://github.com/{source.UPSTREAM}/blob/{commit}/docs/releases.md", notes)
        with self.assertRaises(FileNotFoundError):
            release.release_notes(self.checkout, "v999.0.0", commit)

    def test_release_upgrade_downloads_but_update_redeploys_current_package(self):
        package, _ = self.package()
        preferences = settings.Settings(self.root / "config.toml")
        with (
            patch.object(operations, "ROOT", package),
            patch.object(
                operations,
                "_deploy_controller",
                return_value={"state": "complete", "channel": "release"},
            ) as deploy,
            patch.object(source, "download_release", return_value=package) as download,
            patch("os.geteuid", return_value=0, create=True),
        ):
            result = operations.self_command("upgrade", None, preferences)
            self.assertEqual(result["channel"], "release")
            download.assert_called_once()
            self.assertEqual(deploy.call_args.args, (package, preferences, "release"))
            download.reset_mock()
            operations.self_command("update", None, preferences)
            download.assert_not_called()
            operations.self_command("upgrade", str(package), preferences)
            download.assert_not_called()
            self.assertEqual(
                operations.self_command("status", None, preferences)["channel"], "release"
            )

    def test_native_install_verifier_agrees_with_python_and_refuses_tampering(self):
        package, _ = self.package()
        environment = {
            **os.environ,
            "TEST_ROOT": str(package),
            "TEST_HELPER": str(package / "scripts/verify-source.ps1"),
        }
        if os.name == "nt":
            command = [
                "pwsh",
                "-NoProfile",
                "-Command",
                "$ErrorActionPreference='Stop'; . $env:TEST_HELPER; Assert-DevInfraSource $env:TEST_ROOT",
            ]
        else:
            command = [
                sys.executable,
                "-I",
                "-S",
                str(package / "scripts/verify-source.py"),
                str(package),
            ]
        result = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "release")
        receipt_path = package / source.RECEIPT
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_path.write_text(json.dumps({**receipt, "schema_version": True}), encoding="utf-8")
        result = subprocess.run(
            command, env=environment, capture_output=True, timeout=30, check=False
        )
        self.assertNotEqual(result.returncode, 0)
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        (package / "compose.yaml").write_text("tampered", encoding="utf-8")
        result = subprocess.run(
            command, env=environment, capture_output=True, timeout=30, check=False
        )
        self.assertNotEqual(result.returncode, 0)

    def test_repeated_installer_preserves_external_binding_and_instance_data(self):
        package, _ = self.package()
        deployed, commands = self.root / "deployment", self.root / "commands"
        preferences = self.root / "preferences/config.toml"
        environment = {
            **os.environ,
            "DEV_INFRA_PYTHON": str(Path(sys.executable).resolve()),
            "DEV_INFRA_INSTALL_ROOT": str(deployed),
            "DEV_INFRA_COMMAND_ROOT": str(commands),
            "TEST_INSTALL": str(package / "scripts/install.ps1"),
            "TEST_DEPLOYED": str(deployed),
            "TEST_PREFERENCES": str(preferences),
        }
        if os.name == "nt":
            # Stub the WSL transport, leaving native installation under this test's directory.
            command = [
                "pwsh",
                "-NoProfile",
                "-Command",
                "$ErrorActionPreference='Stop'; function global:wsl.exe { if ($args -contains 'wslpath') { '/isolated-source' }; $global:LASTEXITCODE=0 }; & $env:TEST_INSTALL -AppRoot $env:TEST_DEPLOYED -NoPath -PreferencesPath $env:TEST_PREFERENCES",
            ]
        else:
            if os.geteuid() != 0 or not shutil.which("rsync") or not shutil.which("flock"):
                self.skipTest("Native root, rsync and flock required for isolated installation")
            command = ["bash", str(package / "scripts/install.sh")]

        def install():
            result = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        install()
        kept = {
            ".python": (deployed / ".python").read_bytes(),
            ".env": b"MYSQL_PORT=24306\n",
            "versions.local.env": b"REDIS_VERSION=8\n",
            ".state/retained.json": b'{"retained": true}\n',
            "backup/retained.sql": b"retained backup\n",
            "host/retained.txt": b"legacy private directory\n",
        }
        for name, content in kept.items():
            target = deployed / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        (deployed / "src/dev_infra/obsolete.py").write_text("obsolete code", encoding="utf-8")
        environment.pop("DEV_INFRA_PYTHON")
        install()
        self.assertFalse((deployed / "src/dev_infra/obsolete.py").exists())
        self.assertFalse((deployed / ".source").exists())
        self.assertEqual(source.verify_source(deployed)["channel"], "release")
        for name, content in kept.items():
            self.assertEqual((deployed / name).read_bytes(), content, name)
        self.assertTrue(Path(sys.executable).is_file())
