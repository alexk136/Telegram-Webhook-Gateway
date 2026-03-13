import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
import httpx


os.environ.setdefault("BOT_TOKEN", "123456:test-token")

from app.config import settings
from app.routers.send import router as send_router


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = "ok"

    def json(self):
        return self._payload


class _FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None):
        _FakeAsyncClient.calls.append({"url": url, "json": json, "timeout": self.timeout})
        return _FakeResponse(
            status_code=200,
            payload={
                "ok": True,
                "result": {
                    "message_id": 99,
                },
            },
        )


class SendApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._old_pull_api_token = settings.PULL_API_TOKEN
        self._old_bot_token = settings.BOT_TOKEN
        self._old_default_chat_id = settings.DEFAULT_CHAT_ID
        self._old_bot_token_by_key = settings.BOT_TOKEN_BY_KEY
        self._old_default_chat_by_key = settings.DEFAULT_CHAT_ID_BY_KEY

        settings.PULL_API_TOKEN = "pull-secret"
        settings.BOT_TOKEN = "123456:test-token"
        settings.DEFAULT_CHAT_ID = 777
        settings.BOT_TOKEN_BY_KEY = {"secondary": "654321:sec-token"}
        settings.DEFAULT_CHAT_ID_BY_KEY = {"secondary": 888}

        _FakeAsyncClient.calls = []

        app = FastAPI()
        app.include_router(send_router)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        settings.PULL_API_TOKEN = self._old_pull_api_token
        settings.BOT_TOKEN = self._old_bot_token
        settings.DEFAULT_CHAT_ID = self._old_default_chat_id
        settings.BOT_TOKEN_BY_KEY = self._old_bot_token_by_key
        settings.DEFAULT_CHAT_ID_BY_KEY = self._old_default_chat_by_key

    async def test_send_requires_auth(self):
        response = await self.client.post("/api/send", json={"text": "hello"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})

    async def test_send_uses_defaults_when_key_and_chat_missing(self):
        with patch("app.routers.send.httpx.AsyncClient", _FakeAsyncClient):
            response = await self.client.post(
                "/api/send",
                json={"text": "hello"},
                headers={"Authorization": "Bearer pull-secret"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["chat_id"], 777)
        self.assertEqual(body["bot_id"], "123456")
        self.assertEqual(body["message_id"], 99)

        self.assertEqual(len(_FakeAsyncClient.calls), 1)
        self.assertEqual(
            _FakeAsyncClient.calls[0]["url"],
            "https://api.telegram.org/bot123456:test-token/sendMessage",
        )
        self.assertEqual(_FakeAsyncClient.calls[0]["json"]["chat_id"], 777)
        self.assertEqual(_FakeAsyncClient.calls[0]["json"]["text"], "hello")

    async def test_send_uses_key_mapping_and_chat_override(self):
        with patch("app.routers.send.httpx.AsyncClient", _FakeAsyncClient):
            response = await self.client.post(
                "/api/send",
                json={"text": "hello", "key": "secondary", "chat_id": 999},
                headers={"Authorization": "Bearer pull-secret"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["chat_id"], 999)
        self.assertEqual(body["bot_id"], "654321")
        self.assertEqual(body["key_used"], "secondary")

    async def test_send_unknown_key_returns_404(self):
        response = await self.client.post(
            "/api/send",
            json={"text": "hello", "key": "missing"},
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Unknown key"})

    async def test_send_without_default_chat_returns_400(self):
        settings.DEFAULT_CHAT_ID = None
        settings.DEFAULT_CHAT_ID_BY_KEY = {}

        response = await self.client.post(
            "/api/send",
            json={"text": "hello"},
            headers={"Authorization": "Bearer pull-secret"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "chat_id is required when no default is configured"},
        )


if __name__ == "__main__":
    unittest.main()
