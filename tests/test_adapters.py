import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dev_infra import InfraError, cli
from dev_infra.docker import Docker
from dev_infra.instance import Instance
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

    def test_duplicate_volumes_and_unknown_env_fields_are_rejected(self):
        for content in ("REDIS_DATA_VOLUME=dev-infra-mysql84-data\n", "PATH=/unexpected\n"):
            self.instance.env_path.write_text(content, encoding="utf-8")
            with self.subTest(content=content), self.assertRaises(InfraError):
                Instance(self.root)

    @unittest.skipUnless(os.name == "nt", "Native Windows transport")
    def test_transport_passes_preferences_without_passing_the_config_file(self):
        preferences = Settings(Path("not-forwarded.toml"), language="en", backup=False)
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(cli.forward(["list", "--json"], preferences), 0)
        argv = run.call_args.args[0]
        self.assertIn("DEV_INFRA_TRANSPORT_LANGUAGE=en", argv)
        self.assertIn("DEV_INFRA_BACKUP=false", argv)
        self.assertNotIn(str(preferences.path), argv)


if __name__ == "__main__":
    unittest.main()
