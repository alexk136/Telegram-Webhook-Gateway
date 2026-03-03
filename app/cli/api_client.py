from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


class ClientConfigError(ValueError):
    pass


class GatewayApiClientError(Exception):
    pass


class AuthorizationError(GatewayApiClientError):
    pass


class TemporaryNetworkError(GatewayApiClientError):
    pass


class NonRetryableHttpError(GatewayApiClientError):
    def __init__(self, *, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class ResponseParseError(GatewayApiClientError):
    pass


RETRYABLE_HTTP_CODES = {502, 503, 504}


@dataclass(frozen=True)
class RequestOptions:
    max_retries: int = 2
    retry_backoff_sec: float = 0.25


class GatewayApiClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_sec: float = 10.0,
        pull_api_token: str,
        client: httpx.AsyncClient | None = None,
        max_http_retries: int = 2,
        retry_backoff_sec: float = 0.25,
    ):
        self.base_url = base_url.rstrip("/").strip()
        self.pull_api_token = pull_api_token.strip()
        self.request_options = RequestOptions(
            max_retries=max_http_retries,
            retry_backoff_sec=retry_backoff_sec,
        )

        if not self.base_url:
            raise ClientConfigError("SERVER_BASE_URL is required")
        if not self.pull_api_token:
            raise ClientConfigError("PULL_API_TOKEN must be configured for GatewayApiClient")
        if timeout_sec <= 0:
            raise ClientConfigError("REQUEST_TIMEOUT_SEC must be > 0")
        if self.request_options.max_retries < 0:
            raise ClientConfigError("max_http_retries must be >= 0")
        if self.request_options.retry_backoff_sec < 0:
            raise ClientConfigError("retry_backoff_sec must be >= 0")

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
        payload = {
            "bot_id": bot_id,
            "consumer_id": consumer_id,
            "limit": limit,
            "lease_seconds": lease_seconds,
        }
        data = await self._request("POST", "/api/pull", json=payload)
        items = data.get("items")
        if not isinstance(items, list):
            raise ResponseParseError("/api/pull response must contain list field 'items'")
        return list(items)

    async def ack_update(self, *, message_id: int, consumer_id: str) -> dict[str, Any]:
        return await self.ack_updates(message_ids=[message_id], consumer_id=consumer_id)

    async def ack_updates(self, *, message_ids: list[int], consumer_id: str) -> dict[str, Any]:
        payload = {"message_ids": message_ids, "consumer_id": consumer_id}
        data = await self._request("POST", "/api/ack", json=payload)
        if not isinstance(data, dict):
            raise ResponseParseError("/api/ack response must be a JSON object")
        return data

    async def nack_update(
        self,
        *,
        message_id: int,
        consumer_id: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        return await self.nack_updates(
            message_ids=[message_id],
            consumer_id=consumer_id,
            error=error,
        )

    async def nack_updates(
        self,
        *,
        message_ids: list[int],
        consumer_id: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message_ids": message_ids,
            "consumer_id": consumer_id,
        }
        if error:
            payload["error"] = error

        data = await self._request("POST", "/api/nack", json=payload)
        if not isinstance(data, dict):
            raise ResponseParseError("/api/nack response must be a JSON object")
        return data

    async def get_stats(self, *, bot_id: str | None = None) -> dict[str, Any]:
        return await self.get_stats_with_meta(bot_id=bot_id)

    async def get_stats_with_meta(self, *, bot_id: str | None = None) -> dict[str, Any]:
        params: dict[str, str] | None = None
        if bot_id is not None:
            params = {"bot_id": bot_id}
        try:
            data = await self._request("GET", "/api/pull/stats", params=params)
            endpoint = "/api/pull/stats"
        except NonRetryableHttpError as exc:
            if exc.status_code != 404:
                raise
            data = await self._request("GET", "/stats")
            endpoint = "/stats"

        if not isinstance(data, dict):
            raise ResponseParseError(f"{endpoint} response must be a JSON object")
        normalized = dict(data)
        normalized["_meta"] = {"endpoint": endpoint, "reachable": True, "auth": "ok"}
        return normalized

    async def pull_stats(self, *, bot_id: str | None = None) -> dict[str, Any]:
        return await self.get_stats_with_meta(bot_id=bot_id)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        for attempt in range(self.request_options.max_retries + 1):
            try:
                response = await self._client.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.request_options.max_retries:
                    raise TemporaryNetworkError(f"{method} {path} failed: {exc}") from exc
                await self._sleep_backoff(attempt)
                continue

            status_code = response.status_code
            if status_code in RETRYABLE_HTTP_CODES:
                if attempt >= self.request_options.max_retries:
                    raise TemporaryNetworkError(
                        f"{method} {path} failed with retryable status {status_code}"
                    )
                await self._sleep_backoff(attempt)
                continue

            if status_code in (401, 403):
                raise AuthorizationError(f"Unauthorized request to {path}: HTTP {status_code}")

            if status_code >= 400:
                raise NonRetryableHttpError(status_code=status_code, body=_safe_text(response))

            try:
                payload = response.json()
            except ValueError as exc:
                raise ResponseParseError(f"Failed to parse JSON response for {path}") from exc

            if not isinstance(payload, dict):
                raise ResponseParseError(f"JSON response for {path} must be an object")
            return payload

        raise TemporaryNetworkError(f"{method} {path} failed after retries")

    async def _sleep_backoff(self, attempt: int) -> None:
        if self.request_options.retry_backoff_sec <= 0:
            return
        await asyncio.sleep(self.request_options.retry_backoff_sec * (attempt + 1))

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.pull_api_token}"}


# Backward-compatible alias used by existing CLI code.
PullApiClient = GatewayApiClient


def _safe_text(response: httpx.Response) -> str:
    text = response.text.strip()
    if len(text) <= 500:
        return text
    return text[:500] + "...(truncated)"
