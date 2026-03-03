from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.queue.sqlite import SQLiteQueue


logger = logging.getLogger("pull-cleanup")


async def run_pull_inbox_cleanup_once(*, queue: SQLiteQueue) -> dict[str, int]:
    result = await queue.run_pull_inbox_cleanup(
        acked_retention_days=settings.PULL_INBOX_ACKED_RETENTION_DAYS,
        dead_retention_days=settings.PULL_INBOX_DEAD_RETENTION_DAYS,
        batch_size=settings.PULL_INBOX_CLEANUP_BATCH_SIZE,
    )
    logger.info(
        "pull inbox cleanup completed: deleted_acked=%s deleted_dead=%s "
        "acked_retention_days=%s dead_retention_days=%s batch_size=%s "
        "acked_missing_timestamp=%s",
        result["deleted_acked"],
        result["deleted_dead"],
        settings.PULL_INBOX_ACKED_RETENTION_DAYS,
        settings.PULL_INBOX_DEAD_RETENTION_DAYS,
        settings.PULL_INBOX_CLEANUP_BATCH_SIZE,
        result["acked_missing_timestamp"],
    )
    if result["acked_missing_timestamp"] > 0:
        logger.warning(
            "pull inbox cleanup anomaly: acked rows without acked_at=%s",
            result["acked_missing_timestamp"],
        )
    return result


async def pull_inbox_cleanup_loop(*, queue: SQLiteQueue) -> None:
    while True:
        try:
            await run_pull_inbox_cleanup_once(queue=queue)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pull inbox cleanup loop failed")
        await asyncio.sleep(settings.PULL_INBOX_CLEANUP_INTERVAL_SEC)


def utc_iso_or_none(ts: float | None) -> str | None:
    if ts is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
