import os
import unittest

from fastapi import FastAPI
import httpx


os.environ.setdefault("BOT_TOKEN", "123456:test-token")

import app.state as state
from app.config import settings
from app.routers.pull import router as pull_router


class _FakeQueue:
    def __init__(self):
        self.lease_calls = 0
        self.ack_calls = 0
        self.nack_calls = 0

    async def lease_pull(self, *, consumer_id, lease_seconds, limit, bot_id):
        self.lease_calls += 1
        return [
            {
                "id": 1,
                "source_update_id": 1,
                "bot_id": bot_id,
                "telegram_update_id": 1001,
                "payload_json": {"ok": True},
                "status": "leased",
                "consumer_id": consumer_id,
                "lease_until": 2_000_000_000,
                "retry_count": 0,
                "received_at": 1_999_999_000,
                "acked_at": None,
                "last_error": None,
            }
        ][:limit]

    async def ack_pull_batch(self, *, message_ids, consumer_id):
        self.ack_calls += 1
        return {
            "acked_ids": list(message_ids),
            "already_acked_ids": [],
            "rejected": [],
        }

    async def nack_pull_batch(self, *, message_ids, consumer_id, error=None, max_pull_retries=5):
        self.nack_calls += 1
        return {
            "requested": len(message_ids),
            "nacked": len(message_ids),
            "skipped": 0,
            "results": [{"message_id": m, "status": "nacked"} for m in message_ids],
        }


class PullAuthApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_queue_backend = settings.QUEUE_BACKEND
        self._old_pull_api_token = settings.PULL_API_TOKEN
        self._old_bot_token = settings.BOT_TOKEN
        self._old_queue = state.queue

        settings.QUEUE_BACKEND = "sqlite"
        settings.PULL_API_TOKEN = "pull-secret"
        settings.BOT_TOKEN = "123456:test-token"
        self.bot_id = settings.BOT_TOKEN.split(":", 1)[0]

        self.fake_queue = _FakeQueue()
        state.queue = self.fake_queue

        app = FastAPI()
        app.include_router(pull_router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        settings.QUEUE_BACKEND = self._old_queue_backend
        settings.PULL_API_TOKEN = self._old_pull_api_token
        settings.BOT_TOKEN = self._old_bot_token
        state.queue = self._old_queue

    async def test_pull_unauthorized_variants_return_401(self):
        payload = {
            "bot_id": self.bot_id,
            "consumer_id": "consumer-A",
            "limit": 1,
            "lease_seconds": 30,
        }
        bad_headers = [
            {},
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer"},
            {"Authorization": "Bearer   "},
            {"Authorization": "Bearer wrong-token"},
            {"Authorization": "bearer pull-secret"},
        ]

        for headers in bad_headers:
            with self.subTest(headers=headers):
                response = await self.client.post("/api/pull", json=payload, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json(), {"detail": "Unauthorized"})

        self.assertEqual(self.fake_queue.lease_calls, 0)

    async def test_pull_with_valid_token_works(self):
        response = await self.client.post(
            "/api/pull",
            json={
                "bot_id": self.bot_id,
                "consumer_id": "consumer-A",
                "limit": 1,
                "lease_seconds": 30,
            },
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertIn("server_time", body)
        self.assertEqual(body["messages"][0]["id"], 1)
        self.assertEqual(body["messages"][0]["bot_id"], self.bot_id)
        self.assertEqual(body["messages"][0]["telegram_update_id"], 1001)
        self.assertEqual(body["messages"][0]["payload"], {"ok": True})
        self.assertTrue(body["messages"][0]["lease_until"].endswith("Z"))
        self.assertEqual(self.fake_queue.lease_calls, 1)

    async def test_pull_empty_queue_returns_200_and_empty_messages(self):
        self.fake_queue.lease_pull = _empty_lease_pull  # type: ignore[method-assign]
        response = await self.client.post(
            "/api/pull",
            json={
                "bot_id": self.bot_id,
                "consumer_id": "consumer-A",
                "limit": 1,
                "lease_seconds": 30,
            },
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["messages"], [])
        self.assertEqual(body["count"], 0)
        self.assertIn("server_time", body)

    async def test_ack_requires_token_and_has_no_side_effects_on_401(self):
        payload = {"consumer_id": "consumer-A", "message_ids": [1]}

        response = await self.client.post("/api/ack", json=payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})
        self.assertEqual(self.fake_queue.ack_calls, 0)

        ok_response = await self.client.post(
            "/api/ack",
            json=payload,
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(ok_response.status_code, 200)
        self.assertEqual(self.fake_queue.ack_calls, 1)

    async def test_nack_requires_token_and_has_no_side_effects_on_401(self):
        payload = {"consumer_id": "consumer-A", "message_ids": [1], "error": "boom"}

        response = await self.client.post("/api/nack", json=payload)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})
        self.assertEqual(self.fake_queue.nack_calls, 0)

        ok_response = await self.client.post(
            "/api/nack",
            json=payload,
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(ok_response.status_code, 200)
        self.assertEqual(self.fake_queue.nack_calls, 1)


async def _empty_lease_pull(*, consumer_id, lease_seconds, limit, bot_id):
    return []


if __name__ == "__main__":
    unittest.main()
