import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.cli.main import _main_async, build_parser


class _FakeApiClient:
    def __init__(self, *, base_url, pull_api_token):
        self.base_url = base_url
        self.pull_api_token = pull_api_token
        self.closed = False

    async def pull_updates(self, *, bot_id, consumer_id, limit, lease_seconds):
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
        os.environ["CLI_BOT_ID"] = "123456"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_parser_knows_required_commands(self):
        parser = build_parser()
        args = parser.parse_args(["pull-once"])
        self.assertEqual(args.command, "pull-once")
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


if __name__ == "__main__":
    unittest.main()
