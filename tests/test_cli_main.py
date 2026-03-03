import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.cli.api_client import TemporaryNetworkError
from app.cli.config import CLIConfig
from app.cli.main import _main_async, build_parser, run_poll


class _FakeApiClient:
    def __init__(self, *, base_url, pull_api_token, timeout_sec=10.0):
        self.base_url = base_url
        self.pull_api_token = pull_api_token
        self.timeout_sec = timeout_sec
        self.closed = False
        self.pull_calls = 0

    async def pull_updates(self, *, bot_id, consumer_id, limit, lease_seconds):
        self.pull_calls += 1
        return [{"id": 1}] if limit > 0 else []

    async def pull_stats(self, *, bot_id=None):
        return {"pull_inbox": {"bot_id": bot_id, "new_count": 1}, "generated_at": "2026-03-03T00:00:00Z"}

    async def ack_updates(self, *, message_ids, consumer_id):
        return {"ok": True}

    async def nack_updates(self, *, message_ids, consumer_id, error=None):
        return {"ok": True}

    async def close(self):
        self.closed = True


class CLIMainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        os.environ["PULL_API_TOKEN"] = "tok"
        os.environ["BOT_ID"] = "123456"
        os.environ["CONSUMER_ID"] = "consumer-A"
        os.environ["SERVER_BASE_URL"] = "http://127.0.0.1:8000"
        os.environ["LOCAL_WEBHOOK_URL"] = "http://127.0.0.1:9000/telegram/inbox"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_parser_knows_required_commands(self):
        parser = build_parser()
        args = parser.parse_args(["pull-once"])
        self.assertEqual(args.command, "pull-once")
        args = parser.parse_args(["pull-once", "--forward"])
        self.assertTrue(args.forward)
        args = parser.parse_args(["poll"])
        self.assertEqual(args.command, "poll")
        args = parser.parse_args(["stats"])
        self.assertEqual(args.command, "stats")

    async def test_pull_once_command_dispatches(self):
        with patch("app.cli.main.PullApiClient", _FakeApiClient):
            out = io.StringIO()
            with redirect_stdout(out):
                code = await _main_async(["pull-once"])
        self.assertEqual(code, 0)
        self.assertIn('"command": "pull-once"', out.getvalue())

    async def test_stats_command_dispatches(self):
        with patch("app.cli.main.PullApiClient", _FakeApiClient):
            out = io.StringIO()
            with redirect_stdout(out):
                code = await _main_async(["stats"])
        self.assertEqual(code, 0)
        self.assertIn('"pull_inbox"', out.getvalue())

    async def test_poll_command_dispatches(self):
        with patch("app.cli.main.PullApiClient", _FakeApiClient):
            out = io.StringIO()
            with redirect_stdout(out):
                code = await _main_async(["poll", "--iterations", "1"])
        self.assertEqual(code, 0)
        self.assertIn('"command": "poll"', out.getvalue())

    async def test_run_poll_continues_after_temporary_error(self):
        class _FlakyApi:
            def __init__(self):
                self.calls = 0

            async def pull_updates(self, *, bot_id, consumer_id, limit, lease_seconds):
                self.calls += 1
                if self.calls == 1:
                    raise TemporaryNetworkError("temporary")
                return []

            async def ack_updates(self, *, message_ids, consumer_id):
                return {"ok": True}

            async def nack_updates(self, *, message_ids, consumer_id, error=None):
                return {"ok": True}

        cfg = CLIConfig(
            server_base_url="http://127.0.0.1:8000",
            pull_api_token="tok",
            bot_id="123456",
            consumer_id="consumer-A",
            batch_size=10,
            lease_seconds=30,
            poll_interval_sec=0.01,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            request_timeout_sec=10.0,
            error_backoff_initial_sec=1.0,
            error_backoff_max_sec=10.0,
            error_backoff_multiplier=2.0,
        )
        api = _FlakyApi()
        out = io.StringIO()
        with patch("app.cli.main.asyncio.sleep", return_value=None):
            with redirect_stdout(out):
                code = await run_poll(cfg=cfg, api_client=api, iterations=2)
        self.assertEqual(code, 0)
        self.assertEqual(api.calls, 2)

    async def test_run_poll_applies_backoff_and_resets_on_success(self):
        class _FlakyApi:
            def __init__(self):
                self.calls = 0

            async def pull_updates(self, *, bot_id, consumer_id, limit, lease_seconds):
                self.calls += 1
                if self.calls <= 2:
                    raise TemporaryNetworkError("temporary")
                return []

            async def ack_updates(self, *, message_ids, consumer_id):
                return {"ok": True}

            async def nack_updates(self, *, message_ids, consumer_id, error=None):
                return {"ok": True}

        cfg = CLIConfig(
            server_base_url="http://127.0.0.1:8000",
            pull_api_token="tok",
            bot_id="123456",
            consumer_id="consumer-A",
            batch_size=10,
            lease_seconds=30,
            poll_interval_sec=0.2,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            request_timeout_sec=10.0,
            error_backoff_initial_sec=1.0,
            error_backoff_max_sec=5.0,
            error_backoff_multiplier=2.0,
        )
        api = _FlakyApi()
        delays: list[float] = []

        async def _fake_sleep(delay):
            delays.append(float(delay))

        out = io.StringIO()
        with patch("app.cli.main.asyncio.sleep", side_effect=_fake_sleep):
            with redirect_stdout(out):
                code = await run_poll(cfg=cfg, api_client=api, iterations=3)

        self.assertEqual(code, 0)
        self.assertEqual(api.calls, 3)
        self.assertEqual(delays, [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
