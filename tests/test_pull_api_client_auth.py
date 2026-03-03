import os
import unittest

from app.cli.api_client import PullApiClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self):
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        if url.endswith("/api/pull"):
            return _FakeResponse({"items": []})
        if url.endswith("/api/ack"):
            return _FakeResponse({"ok": True})
        return _FakeResponse({"ok": True})

    async def aclose(self):
        return None


class PullApiClientAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_adds_bearer_header_to_all_requests(self):
        fake_client = _FakeAsyncClient()
        client = PullApiClient(
            base_url="http://localhost:8080",
            pull_api_token="tok-123",
            client=fake_client,
        )

        await client.pull_updates(
            bot_id="123456",
            consumer_id="consumer-A",
            limit=1,
            lease_seconds=30,
        )
        await client.ack_updates(message_ids=[1], consumer_id="consumer-A")
        await client.nack_updates(message_ids=[1], consumer_id="consumer-A", error="boom")

        self.assertEqual(len(fake_client.calls), 3)
        for call in fake_client.calls:
            self.assertEqual(call["headers"].get("Authorization"), "Bearer tok-123")

    async def test_client_reads_token_from_env(self):
        old = os.environ.get("PULL_API_TOKEN")
        os.environ["PULL_API_TOKEN"] = "env-token"
        try:
            fake_client = _FakeAsyncClient()
            client = PullApiClient(
                base_url="http://localhost:8080",
                client=fake_client,
            )
            await client.ack_updates(message_ids=[1], consumer_id="consumer-A")
            self.assertEqual(
                fake_client.calls[0]["headers"].get("Authorization"),
                "Bearer env-token",
            )
        finally:
            if old is None:
                os.environ.pop("PULL_API_TOKEN", None)
            else:
                os.environ["PULL_API_TOKEN"] = old

    def test_client_requires_token(self):
        old = os.environ.get("PULL_API_TOKEN")
        if "PULL_API_TOKEN" in os.environ:
            del os.environ["PULL_API_TOKEN"]
        try:
            with self.assertRaises(ValueError):
                PullApiClient(base_url="http://localhost:8080")
        finally:
            if old is not None:
                os.environ["PULL_API_TOKEN"] = old


if __name__ == "__main__":
    unittest.main()
