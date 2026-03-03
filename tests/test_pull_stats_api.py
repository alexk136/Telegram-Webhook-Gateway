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
        self.stats_calls = []
        self.lease_calls = 0
        self.ack_calls = 0
        self.nack_calls = 0

    async def pull_inbox_stats(self, *, bot_id=None):
        self.stats_calls.append(bot_id)
        if bot_id == "654321":
            return {
                "new_count": 1,
                "leased_count": 0,
                "acked_count": 5,
                "dead_count": 2,
                "expired_leases": 0,
            }
        return {
            "new_count": 3,
            "leased_count": 2,
            "acked_count": 7,
            "dead_count": 1,
            "expired_leases": 1,
        }

    async def lease_pull(self, *, consumer_id, lease_seconds, limit, bot_id):
        self.lease_calls += 1
        return []

    async def ack_pull_batch(self, *, message_ids, consumer_id):
        self.ack_calls += 1
        return {"acked_ids": [], "already_acked_ids": [], "rejected": []}

    async def nack_pull_batch(self, *, message_ids, consumer_id, error=None, max_pull_retries=5):
        self.nack_calls += 1
        return {"requested": 0, "nacked": 0, "skipped": 0, "results": []}


class PullStatsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_queue_backend = settings.QUEUE_BACKEND
        self._old_pull_api_token = settings.PULL_API_TOKEN
        self._old_bot_token = settings.BOT_TOKEN
        self._old_bot_context = settings.BOT_CONTEXT_BY_KEY
        self._old_queue = state.queue

        settings.QUEUE_BACKEND = "sqlite"
        settings.PULL_API_TOKEN = "pull-secret"
        settings.BOT_TOKEN = "123456:test-token"
        settings.BOT_CONTEXT_BY_KEY = {"secondary": "654321"}

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
        settings.BOT_CONTEXT_BY_KEY = self._old_bot_context
        state.queue = self._old_queue

    async def test_stats_requires_auth(self):
        response = await self.client.get("/api/pull/stats")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})
        self.assertEqual(self.fake_queue.stats_calls, [])

    async def test_stats_returns_aggregates(self):
        response = await self.client.get(
            "/api/pull/stats",
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(
            body["pull_inbox"],
            {
                "bot_id": None,
                "new_count": 3,
                "leased_count": 2,
                "acked_count": 7,
                "dead_count": 1,
                "expired_leases": 1,
            },
        )
        self.assertTrue(body["generated_at"].endswith("Z"))
        self.assertEqual(self.fake_queue.stats_calls, [None])
        self.assertEqual(self.fake_queue.lease_calls, 0)
        self.assertEqual(self.fake_queue.ack_calls, 0)
        self.assertEqual(self.fake_queue.nack_calls, 0)

    async def test_stats_supports_bot_filter(self):
        response = await self.client.get(
            "/api/pull/stats?bot_id=654321",
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pull_inbox"]["bot_id"], "654321")
        self.assertEqual(body["pull_inbox"]["new_count"], 1)
        self.assertEqual(self.fake_queue.stats_calls, ["654321"])

    async def test_stats_unknown_bot_returns_404(self):
        response = await self.client.get(
            "/api/pull/stats?bot_id=unknown",
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Unknown bot_id"})
        self.assertEqual(self.fake_queue.stats_calls, [])


if __name__ == "__main__":
    unittest.main()
