from __future__ import annotations

import json
from typing import Any

import httpx

from app.cli.config import CLIConfig
from app.cli.forwarder import forward_to_local_webhook


def _message_view(msg: dict[str, Any]) -> dict[str, Any]:
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    update_kind = "unknown"
    for key in ("message", "edited_message", "callback_query", "inline_query"):
        if key in payload:
            update_kind = key
            break

    return {
        "pull_message_id": msg.get("id"),
        "bot_id": msg.get("bot_id"),
        "telegram_update_id": msg.get("telegram_update_id"),
        "update_kind": update_kind,
    }


async def run_pull_once_command(*, cfg: CLIConfig, api_client: Any, forward: bool) -> int:
    items = await api_client.pull_updates(
        bot_id=cfg.bot_id,
        consumer_id=cfg.consumer_id,
        limit=cfg.batch_size,
        lease_seconds=cfg.lease_seconds,
    )

    if not items:
        print(json.dumps({"command": "pull-once", "count": 0, "message": "no messages"}))
        return 0

    views = [_message_view(item) for item in items]

    if not forward:
        print(
            json.dumps(
                {
                    "command": "pull-once",
                    "count": len(items),
                    "bot_id": cfg.bot_id,
                    "items": views,
                }
            )
        )
        return 0

    if not cfg.local_webhook_url:
        raise ValueError("LOCAL_WEBHOOK_URL is required for pull-once --forward")

    results: list[dict[str, Any]] = []
    has_failures = False
    async with httpx.AsyncClient(timeout=cfg.request_timeout_sec) as local_client:
        for item, view in zip(items, views):
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            fr = await forward_to_local_webhook(
                client=local_client,
                local_webhook_url=cfg.local_webhook_url,
                payload=payload,
            )
            result = {
                **view,
                "forward_ok": fr.success,
                "http_status": fr.status_code,
                "error": fr.error,
            }
            results.append(result)
            if not fr.success:
                has_failures = True

    print(
        json.dumps(
            {
                "command": "pull-once",
                "mode": "forward",
                "count": len(items),
                "bot_id": cfg.bot_id,
                "results": results,
            }
        )
    )
    return 1 if has_failures else 0
