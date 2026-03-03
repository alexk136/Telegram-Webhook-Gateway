import aiosqlite
import json
import time
import os
from typing import Optional, Tuple, List, Dict, Any


PULL_STATUSES = ("new", "leased", "acked", "dead")


class SQLiteQueue:
    def __init__(self, path: str):
        self.path = path

    async def init(self):
        dir_path = os.path.dirname(self.path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                created_at INTEGER
            )
            """)
            await db.execute(f"""
            CREATE TABLE IF NOT EXISTS pull_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_update_id INTEGER NOT NULL,
                bot_id TEXT NOT NULL,
                telegram_update_id INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new'
                    CHECK (status IN {PULL_STATUSES}),
                consumer_id TEXT,
                lease_until INTEGER,
                retry_count INTEGER NOT NULL DEFAULT 0,
                received_at INTEGER NOT NULL,
                acked_at INTEGER,
                last_error TEXT
            )
            """)
            await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pull_inbox_status
            ON pull_inbox(status)
            """)
            await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pull_inbox_lease_until
            ON pull_inbox(lease_until)
            """)
            await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_pull_inbox_bot_id
            ON pull_inbox(bot_id)
            """)
            await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_pull_inbox_bot_update
            ON pull_inbox(bot_id, telegram_update_id)
            """)
            await db.commit()

    async def enqueue(self, payload: dict):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO events (payload, created_at) VALUES (?, ?)",
                (json.dumps(payload), int(time.time()))
            )
            await db.commit()

    async def fetch_next(self) -> Optional[Tuple[int, dict, int]]:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("""
                SELECT id, payload, attempts
                FROM events
                ORDER BY id
                LIMIT 1
                """)
            row = await cursor.fetchone()
            if not row:
                return None
            return row[0], json.loads(row[1]), row[2]
        
    async def count(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM events")
            row = await cursor.fetchone()
            return row[0]
        
    async def increment_attempts(self, event_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE events SET attempts = attempts + 1 WHERE id = ?",
                (event_id,))
            await db.commit()

    async def delete(self, event_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM events WHERE id = ?",
                (event_id,))
            await db.commit()

    async def enqueue_pull(
        self,
        *,
        source_update_id: int,
        bot_id: str,
        telegram_update_id: int,
        payload_json: Dict[str, Any],
    ) -> Optional[int]:
        now = int(time.time())

        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO pull_inbox (
                    source_update_id,
                    bot_id,
                    telegram_update_id,
                    payload_json,
                    status,
                    received_at
                )
                VALUES (?, ?, ?, ?, 'new', ?)
                """,
                (
                    source_update_id,
                    bot_id,
                    telegram_update_id,
                    json.dumps(payload_json),
                    now,
                ),
            )
            await db.commit()
            if cursor.rowcount == 0:
                return None
            return cursor.lastrowid

    async def lease_pull(
        self,
        *,
        consumer_id: str,
        lease_seconds: int,
        limit: int = 1,
        bot_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        now = int(time.time())
        lease_until = now + lease_seconds

        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")

            query = """
                SELECT id
                FROM pull_inbox
                WHERE (status = 'new' OR (status = 'leased' AND lease_until <= ?))
            """
            params: List[Any] = [now]
            if bot_id is not None:
                query += " AND bot_id = ?"
                params.append(bot_id)
            query += " ORDER BY id LIMIT ?"
            params.append(limit)

            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
            pull_ids = [row[0] for row in rows]

            if not pull_ids:
                await db.commit()
                return []

            placeholders = ",".join("?" for _ in pull_ids)
            await db.execute(
                f"""
                UPDATE pull_inbox
                SET status = 'leased',
                    consumer_id = ?,
                    lease_until = ?
                WHERE id IN ({placeholders})
                """,
                (consumer_id, lease_until, *pull_ids),
            )

            cursor = await db.execute(
                f"""
                SELECT
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
                FROM pull_inbox
                WHERE id IN ({placeholders})
                ORDER BY id
                """,
                pull_ids,
            )
            leased_rows = await cursor.fetchall()
            await db.commit()

        result: List[Dict[str, Any]] = []
        for row in leased_rows:
            result.append({
                "id": row[0],
                "source_update_id": row[1],
                "bot_id": row[2],
                "telegram_update_id": row[3],
                "payload_json": json.loads(row[4]),
                "status": row[5],
                "consumer_id": row[6],
                "lease_until": row[7],
                "retry_count": row[8],
                "received_at": row[9],
                "acked_at": row[10],
                "last_error": row[11],
            })
        return result

    async def ack_pull(self, *, inbox_id: int, consumer_id: str) -> bool:
        now = int(time.time())

        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                UPDATE pull_inbox
                SET status = 'acked',
                    acked_at = ?,
                    lease_until = NULL
                WHERE id = ?
                  AND status = 'leased'
                  AND consumer_id = ?
                """,
                (now, inbox_id, consumer_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def release_or_dead_pull(
        self,
        *,
        inbox_id: int,
        consumer_id: str,
        dead_after_retries: int,
        last_error: str,
    ) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT retry_count
                FROM pull_inbox
                WHERE id = ?
                  AND status = 'leased'
                  AND consumer_id = ?
                """,
                (inbox_id, consumer_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return False

            next_retry = int(row[0]) + 1
            if next_retry >= dead_after_retries:
                await db.execute(
                    """
                    UPDATE pull_inbox
                    SET status = 'dead',
                        retry_count = ?,
                        lease_until = NULL,
                        last_error = ?
                    WHERE id = ?
                    """,
                    (next_retry, last_error, inbox_id),
                )
            else:
                await db.execute(
                    """
                    UPDATE pull_inbox
                    SET status = 'new',
                        retry_count = ?,
                        consumer_id = NULL,
                        lease_until = NULL,
                        last_error = ?
                    WHERE id = ?
                    """,
                    (next_retry, last_error, inbox_id),
                )

            await db.commit()
            return True
