import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.cli.commands.pull_once import run_pull_once_command
from app.cli.config import CLIConfig
from app.cli.forwarder import ForwardResult


class _FakeApiClient:
    def __init__(self, items):
        self.items = list(items)
        self.pull_calls = 0

    async def pull_updates(self, *, bot_id, consumer_id, limit, lease_seconds):
        self.pull_calls += 1
        return list(self.items)


class PullOnceCommandTests(unittest.IsolatedAsyncioTestCase):
    def _cfg(self, *, local_webhook_url="http://127.0.0.1:9000/telegram/inbox") -> CLIConfig:
        return CLIConfig(
            server_base_url="http://127.0.0.1:8000",
            pull_api_token="tok",
            bot_id="123456",
            consumer_id="consumer-A",
            batch_size=10,
            lease_seconds=30,
            poll_interval_sec=2.0,
            local_webhook_url=local_webhook_url,
            request_timeout_sec=10.0,
        )

    async def test_pull_once_print_mode_uses_single_pull(self):
        api = _FakeApiClient(
            [
                {
                    "id": 1,
                    "bot_id": "123456",
                    "telegram_update_id": 1001,
                    "payload": {"message": {"text": "hi"}},
                }
            ]
        )
        out = io.StringIO()
        with redirect_stdout(out):
            code = await run_pull_once_command(cfg=self._cfg(), api_client=api, forward=False)

        self.assertEqual(code, 0)
        self.assertEqual(api.pull_calls, 1)
        text = out.getvalue()
        self.assertIn('"command": "pull-once"', text)
        self.assertIn('"pull_message_id": 1', text)
        self.assertIn('"update_kind": "message"', text)

    async def test_pull_once_empty_queue_is_success(self):
        api = _FakeApiClient([])
        out = io.StringIO()
        with redirect_stdout(out):
            code = await run_pull_once_command(cfg=self._cfg(), api_client=api, forward=False)

        self.assertEqual(code, 0)
        self.assertEqual(api.pull_calls, 1)
        self.assertIn('"message": "no messages"', out.getvalue())

    async def test_pull_once_forward_mode(self):
        api = _FakeApiClient(
            [
                {
                    "id": 1,
                    "bot_id": "123456",
                    "telegram_update_id": 1001,
                    "payload": {"message": {"text": "hi"}},
                }
            ]
        )
        out = io.StringIO()
        with patch(
            "app.cli.commands.pull_once.forward_to_local_webhook",
            return_value=ForwardResult(success=True, status_code=200),
        ) as mocked_forward:
            with redirect_stdout(out):
                code = await run_pull_once_command(cfg=self._cfg(), api_client=api, forward=True)

        self.assertEqual(code, 0)
        self.assertEqual(api.pull_calls, 1)
        self.assertEqual(mocked_forward.call_count, 1)
        self.assertIn('"mode": "forward"', out.getvalue())
        self.assertIn('"forward_ok": true', out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
