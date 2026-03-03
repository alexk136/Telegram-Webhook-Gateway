import unittest
import os

from app.queue.sqlite import next_pull_status_after_nack


os.environ.setdefault("BOT_TOKEN", "123:token")

from app.config import Settings


class PullRetryPolicyTests(unittest.TestCase):
    def test_threshold_not_reached_returns_new(self):
        next_retry, status = next_pull_status_after_nack(retry_count=2, max_pull_retries=5)
        self.assertEqual(next_retry, 3)
        self.assertEqual(status, "new")

    def test_threshold_reached_returns_dead(self):
        next_retry, status = next_pull_status_after_nack(retry_count=4, max_pull_retries=5)
        self.assertEqual(next_retry, 5)
        self.assertEqual(status, "dead")

    def test_zero_threshold_goes_dead_on_first_nack(self):
        next_retry, status = next_pull_status_after_nack(retry_count=0, max_pull_retries=0)
        self.assertEqual(next_retry, 1)
        self.assertEqual(status, "dead")


class PullRetryConfigTests(unittest.TestCase):
    def test_default_max_pull_retries(self):
        settings = Settings(BOT_TOKEN="123:token")
        self.assertEqual(settings.MAX_PULL_RETRIES, 5)

    def test_max_pull_retries_accepts_zero(self):
        settings = Settings(BOT_TOKEN="123:token", MAX_PULL_RETRIES=0)
        self.assertEqual(settings.MAX_PULL_RETRIES, 0)

    def test_max_pull_retries_rejects_negative(self):
        with self.assertRaises(ValueError):
            Settings(BOT_TOKEN="123:token", MAX_PULL_RETRIES=-1)


if __name__ == "__main__":
    unittest.main()
