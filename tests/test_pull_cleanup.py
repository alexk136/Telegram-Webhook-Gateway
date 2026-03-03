import tempfile
import time
import unittest
from pathlib import Path

import aiosqlite

from app.queue.sqlite import SQLiteQueue


class PullInboxCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self._tmpdir.name) / "pull_cleanup.db")
        self.queue = SQLiteQueue(self.db_path)
        await self.queue.init()

    async def asyncTearDown(self):
        self._tmpdir.cleanup()

    async def _insert_pull_row(
        self,
        *,
        row_id: int,
        status: str,
        received_at: int,
        acked_at: int | None = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO pull_inbox (
                    id,
                    source_update_id,
                    bot_id,
                    telegram_update_id,
                    payload_json,
                    status,
                    consumer_id,
                    lease_until,
                    retry_count,
                    received_at,
                    acked_at,
                    last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row_id,
                    row_id,
                    f"bot-{row_id}",
                    100000 + row_id,
                    "{}",
                    status,
                    "consumer-x" if status == "leased" else None,
                    received_at + 60 if status == "leased" else None,
                    0,
                    received_at,
                    acked_at,
                    None,
                ),
            )
            await db.commit()

    async def _existing_ids(self) -> set[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT id FROM pull_inbox ORDER BY id")
            rows = await cursor.fetchall()
        return {int(row[0]) for row in rows}

    async def test_cleanup_deletes_old_acked(self):
        now = int(time.time())
        await self._insert_pull_row(
            row_id=1,
            status="acked",
            received_at=now - 1000,
            acked_at=now - (9 * 24 * 60 * 60),
        )
        await self._insert_pull_row(
            row_id=2,
            status="acked",
            received_at=now - 1000,
            acked_at=now - (2 * 24 * 60 * 60),
        )

        result = await self.queue.cleanup_acked(retention_days=7, batch_size=1000)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(await self._existing_ids(), {2})

    async def test_cleanup_deletes_old_dead(self):
        now = int(time.time())
        await self._insert_pull_row(
            row_id=1,
            status="dead",
            received_at=now - (40 * 24 * 60 * 60),
            acked_at=now - (35 * 24 * 60 * 60),
        )
        await self._insert_pull_row(
            row_id=2,
            status="dead",
            received_at=now - (10 * 24 * 60 * 60),
            acked_at=now - (5 * 24 * 60 * 60),
        )

        result = await self.queue.cleanup_dead(retention_days=30, batch_size=1000)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(await self._existing_ids(), {2})

    async def test_cleanup_does_not_delete_fresh_or_active(self):
        now = int(time.time())
        await self._insert_pull_row(row_id=1, status="new", received_at=now - (90 * 24 * 60 * 60))
        await self._insert_pull_row(row_id=2, status="leased", received_at=now - (90 * 24 * 60 * 60))
        await self._insert_pull_row(
            row_id=3,
            status="acked",
            received_at=now - 1000,
            acked_at=now - (1 * 24 * 60 * 60),
        )
        await self._insert_pull_row(
            row_id=4,
            status="dead",
            received_at=now - (5 * 24 * 60 * 60),
            acked_at=now - (1 * 24 * 60 * 60),
        )

        result = await self.queue.run_pull_inbox_cleanup(
            acked_retention_days=7,
            dead_retention_days=30,
            batch_size=1000,
        )
        self.assertEqual(result["deleted_acked"], 0)
        self.assertEqual(result["deleted_dead"], 0)
        self.assertEqual(await self._existing_ids(), {1, 2, 3, 4})

    async def test_cleanup_handles_empty_table_and_is_idempotent(self):
        first = await self.queue.run_pull_inbox_cleanup(
            acked_retention_days=7,
            dead_retention_days=30,
            batch_size=1000,
        )
        second = await self.queue.run_pull_inbox_cleanup(
            acked_retention_days=7,
            dead_retention_days=30,
            batch_size=1000,
        )
        self.assertEqual(first["deleted_acked"], 0)
        self.assertEqual(first["deleted_dead"], 0)
        self.assertEqual(second["deleted_acked"], 0)
        self.assertEqual(second["deleted_dead"], 0)
        self.assertEqual(await self._existing_ids(), set())

    async def test_cleanup_never_deletes_acked_without_timestamp(self):
        now = int(time.time())
        await self._insert_pull_row(
            row_id=1,
            status="acked",
            received_at=now - (100 * 24 * 60 * 60),
            acked_at=None,
        )
        result = await self.queue.cleanup_acked(retention_days=0, batch_size=1000)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["missing_acked_at"], 1)
        self.assertEqual(await self._existing_ids(), {1})


if __name__ == "__main__":
    unittest.main()
