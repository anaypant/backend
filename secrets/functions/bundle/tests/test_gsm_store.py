import unittest
from unittest.mock import MagicMock, patch

from google.api_core import exceptions as gcp_exceptions

import gsm_store


class WriteVersionPermissionDeniedOnReadTest(unittest.TestCase):
    @patch("gsm_store._project", return_value="proj")
    @patch("gsm_store.secretmanager.SecretManagerServiceClient")
    def test_adds_version_when_read_denied(self, mock_client_cls, _proj):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_secret.return_value = object()

        with patch(
            "gsm_store.read_latest",
            side_effect=gcp_exceptions.PermissionDenied("denied"),
        ):
            name, skipped = gsm_store.write_version("sid", "val")
        self.assertFalse(skipped)
        self.assertIn("secrets/sid", name)
        mock_client.add_secret_version.assert_called_once()


class WriteVersionIdempotentTest(unittest.TestCase):
    @patch("gsm_store._project", return_value="proj")
    @patch("gsm_store.secretmanager.SecretManagerServiceClient")
    def test_skips_version_when_latest_matches(self, mock_client_cls, _proj):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_secret.return_value = object()

        with patch("gsm_store.read_latest", return_value="same"):
            name, skipped = gsm_store.write_version("sid", "same")
        self.assertTrue(skipped)
        self.assertIn("secrets/sid", name)
        mock_client.add_secret_version.assert_not_called()

    @patch("gsm_store._project", return_value="proj")
    @patch("gsm_store.secretmanager.SecretManagerServiceClient")
    def test_adds_version_when_value_differs(self, mock_client_cls, _proj):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_secret.return_value = object()

        with patch("gsm_store.read_latest", return_value="old"):
            name, skipped = gsm_store.write_version("sid", "new")
        self.assertFalse(skipped)
        self.assertIn("secrets/sid", name)
        mock_client.add_secret_version.assert_called_once()

    @patch("gsm_store._project", return_value="proj")
    @patch("gsm_store.secretmanager.SecretManagerServiceClient")
    def test_creates_secret_when_missing(self, mock_client_cls, _proj):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_secret.side_effect = gcp_exceptions.NotFound("x")

        name, skipped = gsm_store.write_version("sid", "first")
        self.assertFalse(skipped)
        mock_client.create_secret.assert_called_once()
        self.assertEqual(mock_client.add_secret_version.call_count, 1)


if __name__ == "__main__":
    unittest.main()
