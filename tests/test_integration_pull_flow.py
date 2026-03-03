import os
import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

import aiosqlite
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

os.environ.setdefault("BOT_TOKEN", "111111:test-token")

import app.state as state
from app.cli.api_client import GatewayApiClient
from app.cli.forwarder import forward_to_local_webhook
from app.config import settings
from app.routers.pull import router as pull_router
from app.webhook import telegram_webhook, telegram_webhook_by_key
from app.queue.sqlite import SQLiteQueue


def _telegram_update(update_id: int, text: str = "hello", chat_id: int = 1) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1_700_000_000,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    }


class PullFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "integration.db")

        self._old_queue = state.queue
        self._old_queue_backend = settings.QUEUE_BACKEND
        self._old_bot_token = settings.BOT_TOKEN
        self._old_bot_context = settings.BOT_CONTEXT_BY_KEY
        self._old_pull_api_token = settings.PULL_API_TOKEN
        self._old_public_mode = settings.PUBLIC_MODE
        self._old_telegram_secret = settings.TELEGRAM_SECRET_TOKEN

        settings.QUEUE_BACKEND = "sqlite"
        settings.BOT_TOKEN = "111111:test-token"
        settings.BOT_CONTEXT_BY_KEY = {"bot_b": "222222"}
        settings.PULL_API_TOKEN = "pull-secret"
        settings.PUBLIC_MODE = True
        settings.TELEGRAM_SECRET_TOKEN = None

        state.queue = SQLiteQueue(self.db_path)
        await state.queue.init()

        self.local_status_code = 200
        self.local_received: list[dict[str, Any]] = []

        app = FastAPI()
        app.include_router(pull_router)
        app.add_api_route("/telegram/webhook", telegram_webhook, methods=["POST"])
        app.add_api_route("/telegram/webhook/{bot_key}", telegram_webhook_by_key, methods=["POST"])

        @app.post("/local/webhook")
        async def local_webhook(request: Request):
            payload = await request.json()
            self.local_received.append(payload)
            return JSONResponse({"ok": self.local_status_code < 400}, status_code=self.local_status_code)

        self.http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )
        self.api_client = GatewayApiClient(
            base_url="http://test",
            pull_api_token="pull-secret",
            client=self.http,
            max_http_retries=0,
        )

    async def asyncTearDown(self):
        await self.api_client.close()
        self._tmpdir.cleanup()
        state.queue = self._old_queue
        settings.QUEUE_BACKEND = self._old_queue_backend
        settings.BOT_TOKEN = self._old_bot_token
        settings.BOT_CONTEXT_BY_KEY = self._old_bot_context
        settings.PULL_API_TOKEN = self._old_pull_api_token
        settings.PUBLIC_MODE = self._old_public_mode
        settings.TELEGRAM_SECRET_TOKEN = self._old_telegram_secret

    async def _ingest(self, update: dict[str, Any], *, bot_key: str | None = None) -> httpx.Response:
        path = "/telegram/webhook" if bot_key is None else f"/telegram/webhook/{bot_key}"
        return await self.http.post(path, json=update)

    async def _pull_row(self, *, bot_id: str, telegram_update_id: int) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT
                    id, bot_id, telegram_update_id, status, consumer_id,
                    lease_until, retry_count, acked_at, last_error
                FROM pull_inbox
                WHERE bot_id = ? AND telegram_update_id = ?
                """,
                (bot_id, telegram_update_id),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "bot_id": row[1],
            "telegram_update_id": int(row[2]),
            "status": row[3],
            "consumer_id": row[4],
            "lease_until": row[5],
            "retry_count": int(row[6]),
            "acked_at": row[7],
            "last_error": row[8],
        }

    async def _pull_count(self, *, bot_id: str, telegram_update_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM pull_inbox WHERE bot_id = ? AND telegram_update_id = ?",
                (bot_id, telegram_update_id),
            )
            row = await cursor.fetchone()
        return int(row[0] or 0)

    async def test_happy_path_ingest_pull_forward_ack(self):
        response = await self._ingest(_telegram_update(1001))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

        row = await self._pull_row(bot_id="111111", telegram_update_id=1001)
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "new")

        pulled = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-A",
            limit=10,
            lease_seconds=30,
        )
        self.assertEqual(len(pulled), 1)
        message = pulled[0]

        leased_row = await self._pull_row(bot_id="111111", telegram_update_id=1001)
        self.assertEqual(leased_row["status"], "leased")
        self.assertEqual(leased_row["consumer_id"], "consumer-A")

        forward_result = await forward_to_local_webhook(
            client=self.http,
            local_webhook_url="http://test/local/webhook",
            msg=message,
        )
        self.assertTrue(forward_result.success)
        self.assertEqual(len(self.local_received), 1)
        self.assertEqual(self.local_received[0]["bot_id"], "111111")
        self.assertEqual(self.local_received[0]["telegram_update_id"], 1001)
        self.assertIsInstance(self.local_received[0]["update"], dict)

        await self.api_client.ack_update(message_id=int(message["id"]), consumer_id="consumer-A")
        acked_row = await self._pull_row(bot_id="111111", telegram_update_id=1001)
        self.assertEqual(acked_row["status"], "acked")
        self.assertIsNotNone(acked_row["acked_at"])

        second_pull = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-A",
            limit=10,
            lease_seconds=30,
        )
        self.assertEqual(second_pull, [])

    async def test_failed_local_webhook_causes_nack_and_redelivery(self):
        await self._ingest(_telegram_update(2002))

        pulled = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-B",
            limit=1,
            lease_seconds=30,
        )
        message = pulled[0]

        self.local_status_code = 500
        forward_result = await forward_to_local_webhook(
            client=self.http,
            local_webhook_url="http://test/local/webhook",
            msg=message,
        )
        self.assertFalse(forward_result.success)

        await self.api_client.nack_update(
            message_id=int(message["id"]),
            consumer_id="consumer-B",
            error=forward_result.error,
        )

        row = await self._pull_row(bot_id="111111", telegram_update_id=2002)
        self.assertEqual(row["status"], "new")
        self.assertEqual(row["retry_count"], 1)
        self.assertIn("local_http_status=500", row["last_error"] or "")

        self.local_status_code = 200
        redelivered = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-B",
            limit=1,
            lease_seconds=30,
        )
        self.assertEqual(len(redelivered), 1)
        self.assertEqual(redelivered[0]["id"], message["id"])

    async def test_lease_expiry_redelivers_without_ack_or_nack(self):
        await self._ingest(_telegram_update(3003))

        first = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-C",
            limit=1,
            lease_seconds=1,
        )
        self.assertEqual(len(first), 1)
        first_id = first[0]["id"]

        second: list[dict[str, Any]] = []
        for _ in range(8):
            await asyncio.sleep(0.35)
            second = await self.api_client.pull_updates(
                bot_id="111111",
                consumer_id="consumer-C",
                limit=1,
                lease_seconds=5,
            )
            if second:
                break

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["id"], first_id)

    async def test_pull_filters_messages_by_bot_id(self):
        await self._ingest(_telegram_update(4004, text="from-a"), bot_key=None)
        await self._ingest(_telegram_update(5005, text="from-b"), bot_key="bot_b")

        pulled_a = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-A",
            limit=10,
            lease_seconds=30,
        )
        pulled_b = await self.api_client.pull_updates(
            bot_id="222222",
            consumer_id="consumer-B",
            limit=10,
            lease_seconds=30,
        )

        self.assertEqual({m["bot_id"] for m in pulled_a}, {"111111"})
        self.assertEqual({m["telegram_update_id"] for m in pulled_a}, {4004})
        self.assertEqual({m["bot_id"] for m in pulled_b}, {"222222"})
        self.assertEqual({m["telegram_update_id"] for m in pulled_b}, {5005})

    async def test_dedup_by_bot_id_and_telegram_update_id(self):
        update = _telegram_update(6006, text="dup")
        first = await self._ingest(update)
        second = await self._ingest(update)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json(), {"ok": True})
        self.assertEqual(second.json(), {"ok": True})

        count = await self._pull_count(bot_id="111111", telegram_update_id=6006)
        self.assertEqual(count, 1)

        pulled = await self.api_client.pull_updates(
            bot_id="111111",
            consumer_id="consumer-D",
            limit=10,
            lease_seconds=30,
        )
        self.assertEqual(len(pulled), 1)
        self.assertEqual(int(pulled[0]["telegram_update_id"]), 6006)


if __name__ == "__main__":
    unittest.main()
