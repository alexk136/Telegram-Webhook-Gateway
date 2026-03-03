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
        self.calls.append({"method": "POST", "url": url, "json": json, "headers": headers or {}})
        if url.endswith("/api/pull"):
            return _FakeResponse({"items": []})
        if url.endswith("/api/ack"):
            return _FakeResponse({"ok": True})
        return _FakeResponse({"ok": True})

    async def get(self, url, params=None, headers=None):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers or {}})
        return _FakeResponse({"pull_inbox": {"new_count": 0}, "generated_at": "2026-03-03T00:00:00Z"})

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
        await client.pull_stats(bot_id="123456")

        self.assertEqual(len(fake_client.calls), 4)
        for call in fake_client.calls:
            self.assertEqual(call["headers"].get("Authorization"), "Bearer tok-123")

    def test_client_requires_token(self):
        with self.assertRaises(TypeError):
            PullApiClient(base_url="http://localhost:8080")


if __name__ == "__main__":
    unittest.main()
