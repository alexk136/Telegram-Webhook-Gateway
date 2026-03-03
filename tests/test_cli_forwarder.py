import unittest

import httpx

from app.cli.forwarder import forward_to_local_webhook
from app.contracts.local_webhook import extract_idempotency_key


class _FakeClient:
    def __init__(self, *, response: httpx.Response | None = None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        if self.exc is not None:
            raise self.exc
        return self.response


class ForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def test_forward_wraps_message_context(self):
        response = httpx.Response(200, request=httpx.Request("POST", "http://local/webhook"))
        client = _FakeClient(response=response)

        result = await forward_to_local_webhook(
            client=client,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            msg={
                "id": 77,
                "bot_id": "123456",
                "telegram_update_id": 1001,
                "payload": {"message": {"text": "hello"}},
            },
        )

        self.assertTrue(result.success)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(
            client.calls[0]["json"],
            {
                "bot_id": "123456",
                "telegram_update_id": 1001,
                "pull_message_id": 77,
                "update": {"message": {"text": "hello"}},
            },
        )
        self.assertEqual(client.calls[0]["headers"].get("Content-Type"), "application/json")

    async def test_forward_accepts_201_202_204_as_success(self):
        for code in (201, 202, 204):
            with self.subTest(status_code=code):
                response = httpx.Response(code, request=httpx.Request("POST", "http://local/webhook"))
                client = _FakeClient(response=response)
                result = await forward_to_local_webhook(
                    client=client,
                    local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
                    msg={
                        "id": 1,
                        "bot_id": "123456",
                        "telegram_update_id": 1001,
                        "payload": {"update_id": 1001},
                    },
                )
                self.assertTrue(result.success)
                self.assertEqual(result.status_code, code)

    async def test_forward_treats_non_2xx_as_failure(self):
        response = httpx.Response(
            500,
            content=b"boom",
            request=httpx.Request("POST", "http://local/webhook"),
        )
        client = _FakeClient(response=response)

        result = await forward_to_local_webhook(
            client=client,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            msg={"id": 1, "bot_id": "123456", "telegram_update_id": 1001, "payload": {}},
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status_code, 500)
        self.assertIn("local_http_status=500", result.error or "")

    async def test_forward_rejects_invalid_message_for_contract(self):
        response = httpx.Response(200, request=httpx.Request("POST", "http://local/webhook"))
        client = _FakeClient(response=response)
        result = await forward_to_local_webhook(
            client=client,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            msg={"id": 1, "telegram_update_id": 1001, "payload": {}},
        )
        self.assertFalse(result.success)
        self.assertIsNone(result.status_code)
        self.assertIn("invalid_forward_payload=", result.error or "")
        self.assertEqual(client.calls, [])

    async def test_forward_transport_error(self):
        req = httpx.Request("POST", "http://local/webhook")
        client = _FakeClient(exc=httpx.ConnectError("refused", request=req))

        result = await forward_to_local_webhook(
            client=client,
            local_webhook_url="http://127.0.0.1:9000/telegram/inbox",
            msg={"id": 1, "bot_id": "123456", "telegram_update_id": 1001, "payload": {}},
        )

        self.assertFalse(result.success)
        self.assertIsNone(result.status_code)
        self.assertIn("exception_class=ConnectError", result.error or "")

    def test_local_handler_extracts_idempotency_key(self):
        payload = {
            "bot_id": "123456",
            "telegram_update_id": 1001,
            "pull_message_id": 77,
            "update": {"update_id": 1001, "message": {"text": "hello"}},
        }
        self.assertEqual(extract_idempotency_key(payload), ("123456", 1001))

    def test_optional_fields_do_not_break_idempotency_parsing(self):
        payload = {
            "bot_id": "123456",
            "telegram_update_id": 1001,
            "pull_message_id": 77,
            "update": {"update_id": 1001, "message": {"text": "hello"}},
            "trace_id": "abc-123",
        }
        self.assertEqual(extract_idempotency_key(payload), ("123456", 1001))


if __name__ == "__main__":
    unittest.main()
