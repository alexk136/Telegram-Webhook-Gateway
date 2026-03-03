from __future__ import annotations
from typing import Any

import httpx


class PullApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_sec: float = 10.0,
        pull_api_token: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.pull_api_token = pull_api_token.strip()
        if not self.pull_api_token:
            raise ValueError("PULL_API_TOKEN must be configured for PullApiClient")
        self._client = client or httpx.AsyncClient(timeout=timeout_sec)

    async def close(self) -> None:
        await self._client.aclose()

    async def pull_updates(
        self,
        *,
        bot_id: str,
        consumer_id: str,
        limit: int,
        lease_seconds: int,
    ) -> list[dict[str, Any]]:
        resp = await self._client.post(
            f"{self.base_url}/api/pull",
            json={
                "bot_id": bot_id,
                "consumer_id": consumer_id,
                "limit": limit,
                "lease_seconds": lease_seconds,
            },
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("items", []))

    async def ack_updates(self, *, message_ids: list[int], consumer_id: str) -> dict[str, Any]:
        resp = await self._client.post(
            f"{self.base_url}/api/ack",
            json={"message_ids": message_ids, "consumer_id": consumer_id},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def nack_updates(
        self,
        *,
        message_ids: list[int],
        consumer_id: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"message_ids": message_ids, "consumer_id": consumer_id}
        if error:
            payload["error"] = error
        resp = await self._client.post(
            f"{self.base_url}/api/nack",
            json=payload,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def pull_stats(self, *, bot_id: str | None = None) -> dict[str, Any]:
        params: dict[str, str] | None = None
        if bot_id is not None:
            params = {"bot_id": bot_id}
        resp = await self._client.get(
            f"{self.base_url}/api/pull/stats",
            params=params,
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.pull_api_token}"}
