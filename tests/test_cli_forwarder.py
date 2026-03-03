import unittest

import httpx

from app.cli.forwarder import forward_to_local_webhook


class _FakeClient:
    def __init__(self, *, response: httpx.Response | None = None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls = []

    async def post(self, url, json=None):
        self.calls.append({"url": url, "json": json})
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


if __name__ == "__main__":
    unittest.main()
