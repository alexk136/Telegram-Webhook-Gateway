import os
import unittest

from app.cli.config import load_cli_config


class CLIConfigTests(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        os.environ["SERVER_BASE_URL"] = "http://127.0.0.1:8000"
        os.environ["PULL_API_TOKEN"] = "token-1234"
        os.environ["BOT_ID"] = "123456"
        os.environ["CONSUMER_ID"] = "consumer-A"
        os.environ["LOCAL_WEBHOOK_URL"] = "http://127.0.0.1:9000/telegram/inbox"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_load_valid_config_from_env(self):
        cfg = load_cli_config(require_local_webhook=True)
        self.assertEqual(cfg.server_base_url, "http://127.0.0.1:8000")
        self.assertEqual(cfg.bot_id, "123456")
        self.assertEqual(cfg.consumer_id, "consumer-A")
        self.assertEqual(cfg.batch_size, 10)
        self.assertEqual(cfg.request_timeout_sec, 10.0)
        self.assertEqual(cfg.error_backoff_initial_sec, 1.0)
        self.assertEqual(cfg.error_backoff_max_sec, 30.0)
        self.assertEqual(cfg.error_backoff_multiplier, 2.0)

    def test_cli_options_override_env(self):
        cfg = load_cli_config(
            server_base_url="https://gateway.example.com",
            batch_size=50,
            poll_interval_sec=3.5,
        )
        self.assertEqual(cfg.server_base_url, "https://gateway.example.com")
        self.assertEqual(cfg.batch_size, 50)
        self.assertEqual(cfg.poll_interval_sec, 3.5)

    def test_missing_bot_id_fails(self):
        os.environ.pop("BOT_ID")
        with self.assertRaisesRegex(ValueError, "BOT_ID is required"):
            load_cli_config()

    def test_invalid_local_webhook_url_fails(self):
        os.environ["LOCAL_WEBHOOK_URL"] = "not-a-url"
        with self.assertRaisesRegex(ValueError, "LOCAL_WEBHOOK_URL must be a valid http/https URL"):
            load_cli_config(require_local_webhook=True)

    def test_invalid_poll_interval_fails(self):
        os.environ["POLL_INTERVAL_SEC"] = "0"
        with self.assertRaisesRegex(ValueError, "POLL_INTERVAL_SEC must be > 0"):
            load_cli_config()

    def test_invalid_backoff_config_fails(self):
        os.environ["ERROR_BACKOFF_INITIAL_SEC"] = "5"
        os.environ["ERROR_BACKOFF_MAX_SEC"] = "1"
        with self.assertRaisesRegex(ValueError, "ERROR_BACKOFF_MAX_SEC must be >= ERROR_BACKOFF_INITIAL_SEC"):
            load_cli_config()

    def test_token_is_masked(self):
        cfg = load_cli_config()
        masked = cfg.masked_dict()
        self.assertNotEqual(masked["PULL_API_TOKEN"], "token-1234")
        self.assertIn("***", str(masked["PULL_API_TOKEN"]))


if __name__ == "__main__":
    unittest.main()
