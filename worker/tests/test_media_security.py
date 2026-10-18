"""Privacy regressions: fixture credentials only; no HTTP or real AI requests."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("media_security_ops", Path(__file__).parents[1] / "media_ops.py")
media = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(media)


class CloudCredentialSecurityTests(unittest.TestCase):
    def options(self, **overrides):
        return {"endpoint": "https://provider.invalid/v1", "cloud_consent": True,
                "api_key": "explicit-job-fixture-key", **overrides}

    def test_explicit_job_key_is_used_without_reading_ambient_credentials(self):
        with patch.dict(os.environ, {"PAPERWORK_API_KEY": "private-ambient-paperwork-fixture",
                                     "GITHUB_TOKEN": "private-ambient-github-fixture"}):
            with patch.object(os.environ, "get", wraps=os.environ.get) as environment_get:
                endpoint, headers = media._cloud_config(self.options())
            self.assertEqual(endpoint, "https://provider.invalid/v1")
            self.assertEqual(headers, {"Authorization": "Bearer explicit-job-fixture-key"})
            environment_get.assert_not_called()

    def test_api_key_env_selector_is_rejected_even_with_explicit_job_key(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "private-ambient-github-fixture",
                                     "PAPERWORK_API_KEY": "private-ambient-paperwork-fixture"}):
            with patch.object(os.environ, "get", wraps=os.environ.get) as environment_get:
                for selector in ("GITHUB_TOKEN", "PAPERWORK_API_KEY", "", None, 17, "private-selector-fixture"):
                    with self.subTest(selector=selector):
                        with self.assertRaisesRegex(ValueError, "api_key_env") as error:
                            media._cloud_config(self.options(api_key_env=selector))
                        self.assertNotIn("private-selector-fixture", str(error.exception))
                        self.assertNotIn("explicit-job-fixture-key", str(error.exception))
            environment_get.assert_not_called()

    def test_missing_job_key_rejects_ambient_keys_with_actionable_private_error(self):
        options = self.options()
        del options["api_key"]
        with patch.dict(os.environ, {"PAPERWORK_API_KEY": "private-ambient-paperwork-fixture",
                                     "GITHUB_TOKEN": "private-ambient-github-fixture"}):
            with patch.object(os.environ, "get", wraps=os.environ.get) as environment_get:
                with self.assertRaises(ValueError) as error:
                    media._cloud_config(options)
            environment_get.assert_not_called()
        message = str(error.exception)
        self.assertIn("options.api_key", message)
        self.assertNotIn("private-ambient", message)
        self.assertNotIn("worker environment", message)

    def test_existing_key_bounds_ascii_and_error_redaction(self):
        for key in ("", None, 17, "private-key-fixture" + "a" * 4096,
                    "private-key-fixture\n", "private-key-fixture\x00", "private-key-fixture\x7f",
                    "private-key-fixtureé"):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(ValueError) as error:
                    media._cloud_config(self.options(api_key=key))
                self.assertNotIn("private-key-fixture", str(error.exception))
        _, headers = media._cloud_config(self.options(api_key="a" * 4096))
        self.assertEqual(headers, {"Authorization": "Bearer " + "a" * 4096})

    def test_existing_cloud_consent_requires_literal_true_before_any_transport(self):
        for consent in (False, None, 1, "true"):
            with self.subTest(consent=consent):
                with patch.object(media, "_http_request") as transport:
                    with self.assertRaisesRegex(ValueError, "cloud_consent"):
                        media._cloud_config(self.options(cloud_consent=consent))
                transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
