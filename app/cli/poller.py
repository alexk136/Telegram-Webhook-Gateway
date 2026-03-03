from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.cli.forwarder import ForwardResult, forward_to_local_webhook


logger = logging.getLogger("cli-poller")


class PullApiClientProto(Protocol):
    async def ack_updates(self, *, message_ids: list[int], consumer_id: str) -> dict[str, Any]:
        ...

    async def nack_updates(
        self,
        *,
        message_ids: list[int],
        consumer_id: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        ...


@dataclass
class PollerCounters:
    pulled_total: int = 0
    forward_success_total: int = 0
    forward_fail_total: int = 0
    acked_total: int = 0
    nacked_total: int = 0
    ack_fail_total: int = 0
    nack_fail_total: int = 0


class PullBridgePoller:
    def __init__(
        self,
        *,
        api_client: PullApiClientProto,
        local_webhook_url: str,
        consumer_id: str,
        local_timeout_sec: float = 10.0,
    ):
        self.api_client = api_client
        self.local_webhook_url = local_webhook_url
        self.consumer_id = consumer_id
        self.local_timeout_sec = local_timeout_sec
        self.counters = PollerCounters()

    async def process_batch(self, messages: list[dict[str, Any]]) -> None:
        self.counters.pulled_total += len(messages)
        async with httpx.AsyncClient(timeout=self.local_timeout_sec) as local_client:
            for msg in messages:
                await self._process_one(local_client=local_client, msg=msg)

    async def _process_one(
        self,
        *,
        local_client: httpx.AsyncClient,
        msg: dict[str, Any],
    ) -> None:
        message_id = int(msg["id"])
        bot_id = str(msg.get("bot_id", ""))
        telegram_update_id = msg.get("telegram_update_id")
        payload = msg.get("payload", {})

        forward_result = await forward_to_local_webhook(
            client=local_client,
            local_webhook_url=self.local_webhook_url,
            payload=payload,
        )

        if forward_result.success:
            self.counters.forward_success_total += 1
            ack_ok = await self._ack_one(message_id=message_id)
            if ack_ok:
                self.counters.acked_total += 1
                outcome = "FORWARDED_OK + ACK_OK"
            else:
                self.counters.ack_fail_total += 1
                outcome = "FORWARDED_OK + ACK_FAIL"
        else:
            self.counters.forward_fail_total += 1
            nack_ok = await self._nack_one(message_id=message_id, forward_result=forward_result)
            if nack_ok:
                self.counters.nacked_total += 1
                outcome = "FORWARDED_FAIL + NACK_OK"
            else:
                self.counters.nack_fail_total += 1
                outcome = "FORWARDED_FAIL + NACK_FAIL"

        logger.info(
            "pull_message_id=%s bot_id=%s telegram_update_id=%s outcome=%s",
            message_id,
            bot_id,
            telegram_update_id,
            outcome,
        )

    async def _ack_one(self, *, message_id: int) -> bool:
        try:
            await self.api_client.ack_updates(
                message_ids=[message_id],
                consumer_id=self.consumer_id,
            )
            return True
        except Exception:
            logger.exception("ACK failed for pull_message_id=%s", message_id)
            return False

    async def _nack_one(self, *, message_id: int, forward_result: ForwardResult) -> bool:
        error = forward_result.error or "forward_failed"
        try:
            await self.api_client.nack_updates(
                message_ids=[message_id],
                consumer_id=self.consumer_id,
                error=error,
            )
            return True
        except Exception:
            logger.exception("NACK failed for pull_message_id=%s", message_id)
            return False

