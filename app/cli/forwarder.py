from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


SUCCESS_HTTP_CODES = {200, 201, 202, 204}


@dataclass
class ForwardResult:
    success: bool
    status_code: int | None = None
    error: str | None = None


def _truncate_body(text: str, limit: int = 300) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...(truncated)"


async def forward_to_local_webhook(
    *,
    client: httpx.AsyncClient,
    local_webhook_url: str,
    msg: dict[str, Any],
) -> ForwardResult:
    update = msg.get("payload")
    if not isinstance(update, dict):
        update = {}

    body = {
        "bot_id": msg.get("bot_id"),
        "telegram_update_id": msg.get("telegram_update_id"),
        "pull_message_id": msg.get("id"),
        "update": update,
    }

    try:
        resp = await client.post(local_webhook_url, json=body)
    except Exception as exc:
        return ForwardResult(
            success=False,
            error=f"exception_class={exc.__class__.__name__}; reason={str(exc)}",
        )

    if resp.status_code in SUCCESS_HTTP_CODES:
        return ForwardResult(success=True, status_code=resp.status_code)

    snippet = _truncate_body(resp.text.strip())
    return ForwardResult(
        success=False,
        status_code=resp.status_code,
        error=(
            f"local_http_status={resp.status_code}; "
            f"response_body_snippet={snippet}"
        ),
    )
