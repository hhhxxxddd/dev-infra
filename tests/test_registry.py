import unittest
from unittest.mock import patch

from dev_infra import InfraError
from dev_infra.catalog import SERVICES
from dev_infra.registry import Registry
from tests.support import DIGEST, metadata


class RegistryTests(unittest.TestCase):
    def test_pagination_ignores_prereleases_and_selects_concrete_tag(self):
        registry = Registry()
        payloads = [
            metadata("18"),
            {"next": "page2", "results": [metadata("18.7-rc.1"), metadata("19.1")]},
            {"next": None, "results": [metadata("18.6")]},
        ]
        with patch.object(registry, "get", side_effect=payloads) as get:
            result = registry.latest(SERVICES["postgres"], "18")
        self.assertEqual(result["name"], "18.6")
        self.assertIn("page=2", get.call_args.args[1])

    def test_pagination_limit_is_reported_as_incomplete(self):
        registry = Registry()
        with (
            patch.object(
                registry,
                "get",
                side_effect=[metadata("18"), *[{"next": "more", "results": []}] * 10],
            ),
            self.assertRaisesRegex(InfraError, "incomplete_registry"),
        ):
            registry.latest(SERVICES["postgres"], "18")

    def test_floating_alias_does_not_hide_concrete_release_on_next_page(self):
        registry = Registry()
        with patch.object(
            registry,
            "get",
            side_effect=[
                metadata("8.4"),
                {"next": "more", "results": [metadata("8.4")]},
                {"next": None, "results": [metadata("8.4.11")]},
            ],
        ):
            self.assertEqual(registry.latest(SERVICES["mysql"], "8.4")["name"], "8.4.11")

    def test_invalid_metadata_fails_before_becoming_an_upgrade_target(self):
        registry = Registry()
        for data in (
            {"name": "18.6", "digest": None},
            {"name": "19.1", "digest": DIGEST},
            {"name": "18.6", "digest": DIGEST, "images": [None]},
        ):
            with (
                self.subTest(data=data),
                patch.object(registry, "get", return_value=data),
                self.assertRaises(InfraError),
            ):
                registry.exact("library/postgres", "18.6")

    def test_major_and_minor_scopes_are_declared_in_the_catalog(self):
        self.assertEqual(SERVICES["mysql"].scope("8.4.11@" + DIGEST), "8.4")
        self.assertEqual(SERVICES["kafka"].scope("4.3.1"), "4.3")
        self.assertEqual(SERVICES["postgres"].scope("18.6"), "18")


if __name__ == "__main__":
    unittest.main()
