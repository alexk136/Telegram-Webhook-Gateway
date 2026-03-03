import unittest

import httpx

from app.cli.api_client import (
    AuthorizationError,
    GatewayApiClient,
    NonRetryableHttpError,
    PullApiClient,
    ResponseParseError,
    TemporaryNetworkError,
)


class _FakeAsyncClient:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []

    async def request(self, method, url, json=None, params=None, headers=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "params": params,
                "headers": headers or {},
            }
        )
        if not self.scripted:
            raise AssertionError("No scripted response left")
        item = self.scripted.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def aclose(self):
        return None


def _json_response(status: int, payload: dict):
    return httpx.Response(
        status_code=status,
        json=payload,
        request=httpx.Request("GET", "http://test"),
    )


def _text_response(status: int, text: str):
    return httpx.Response(
        status_code=status,
        content=text.encode("utf-8"),
        request=httpx.Request("GET", "http://test"),
    )


class PullApiClientAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_adds_bearer_header_and_payloads(self):
        fake = _FakeAsyncClient(
            [
                _json_response(200, {"items": []}),
                _json_response(200, {"ok": True}),
                _json_response(200, {"ok": True}),
                _json_response(200, {"ok": True}),
                _json_response(200, {"ok": True}),
                _json_response(200, {"pull_inbox": {"new_count": 0}, "generated_at": "2026-03-03T00:00:00Z"}),
            ]
        )
        client = PullApiClient(
            base_url="http://localhost:8080/",
            pull_api_token="tok-123",
            client=fake,
        )

        await client.pull_updates(bot_id="123456", consumer_id="consumer-A", limit=1, lease_seconds=30)
        await client.ack_update(message_id=1, consumer_id="consumer-A")
        await client.ack_updates(message_ids=[1, 2], consumer_id="consumer-A")
        await client.nack_update(message_id=1, consumer_id="consumer-A", error="boom")
        await client.nack_updates(message_ids=[1, 2], consumer_id="consumer-A")
        stats = await client.get_stats(bot_id="123456")

        self.assertEqual(len(fake.calls), 6)
        self.assertTrue(all(c["headers"].get("Authorization") == "Bearer tok-123" for c in fake.calls))
        self.assertEqual(fake.calls[0]["url"], "http://localhost:8080/api/pull")
        self.assertEqual(fake.calls[0]["json"]["bot_id"], "123456")
        self.assertEqual(fake.calls[1]["json"]["message_ids"], [1])
        self.assertEqual(fake.calls[2]["json"]["message_ids"], [1, 2])
        self.assertEqual(fake.calls[3]["json"]["error"], "boom")
        self.assertEqual(fake.calls[5]["params"], {"bot_id": "123456"})
        self.assertEqual(stats["_meta"]["endpoint"], "/api/pull/stats")

    async def test_stats_fallback_to_root_stats_on_404(self):
        fake = _FakeAsyncClient(
            [
                _text_response(404, "not found"),
                _json_response(200, {"queued": 3, "dead_count": 1, "uptime_sec": 10}),
            ]
        )
        client = GatewayApiClient(
            base_url="http://localhost:8080",
            pull_api_token="tok",
            client=fake,
            max_http_retries=0,
        )
        stats = await client.get_stats()
        self.assertEqual(stats["_meta"]["endpoint"], "/stats")
        self.assertEqual(stats["queued"], 3)
        self.assertEqual(len(fake.calls), 2)

    async def test_retry_on_timeout_then_success(self):
        req = httpx.Request("POST", "http://localhost:8080/api/pull")
        fake = _FakeAsyncClient(
            [
                httpx.ReadTimeout("timeout", request=req),
                _json_response(200, {"items": []}),
            ]
        )
        client = GatewayApiClient(
            base_url="http://localhost:8080",
            pull_api_token="tok",
            client=fake,
            max_http_retries=1,
            retry_backoff_sec=0,
        )
        items = await client.pull_updates(bot_id="123456", consumer_id="c", limit=1, lease_seconds=10)
        self.assertEqual(items, [])
        self.assertEqual(len(fake.calls), 2)

    async def test_retry_on_503_then_success(self):
        fake = _FakeAsyncClient(
            [
                _json_response(503, {"detail": "temporary"}),
                _json_response(200, {"items": []}),
            ]
        )
        client = GatewayApiClient(
            base_url="http://localhost:8080",
            pull_api_token="tok",
            client=fake,
            max_http_retries=1,
            retry_backoff_sec=0,
        )
        items = await client.pull_updates(bot_id="123456", consumer_id="c", limit=1, lease_seconds=10)
        self.assertEqual(items, [])
        self.assertEqual(len(fake.calls), 2)

    async def test_401_is_authorization_error(self):
        fake = _FakeAsyncClient([_json_response(401, {"detail": "Unauthorized"})])
        client = GatewayApiClient(base_url="http://localhost:8080", pull_api_token="tok", client=fake)
        with self.assertRaises(AuthorizationError):
            await client.pull_updates(bot_id="123456", consumer_id="c", limit=1, lease_seconds=10)

    async def test_400_is_non_retryable_http_error(self):
        fake = _FakeAsyncClient([_text_response(400, "bad request")])
        client = GatewayApiClient(base_url="http://localhost:8080", pull_api_token="tok", client=fake)
        with self.assertRaises(NonRetryableHttpError):
            await client.ack_updates(message_ids=[1], consumer_id="c")

    async def test_invalid_json_response_raises_parse_error(self):
        fake = _FakeAsyncClient([_text_response(200, "not-json")])
        client = GatewayApiClient(base_url="http://localhost:8080", pull_api_token="tok", client=fake)
        with self.assertRaises(ResponseParseError):
            await client.get_stats()

    async def test_retry_exhaustion_raises_temporary_network_error(self):
        req = httpx.Request("POST", "http://localhost:8080/api/pull")
        fake = _FakeAsyncClient(
            [
                httpx.ConnectError("conn", request=req),
                httpx.ConnectError("conn", request=req),
            ]
        )
        client = GatewayApiClient(
            base_url="http://localhost:8080",
            pull_api_token="tok",
            client=fake,
            max_http_retries=1,
            retry_backoff_sec=0,
        )
        with self.assertRaises(TemporaryNetworkError):
            await client.pull_updates(bot_id="123456", consumer_id="c", limit=1, lease_seconds=10)

    def test_client_requires_token(self):
        with self.assertRaises(TypeError):
            PullApiClient(base_url="http://localhost:8080")


if __name__ == "__main__":
    unittest.main()
