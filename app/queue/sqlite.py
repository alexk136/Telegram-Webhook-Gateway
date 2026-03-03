import aiosqlite
import json
import time
import os
import logging
from typing import Optional, Tuple, List, Dict, Any


PULL_STATUSES = ("new", "leased", "acked", "dead")
logger = logging.getLogger("pull-queue")


def next_pull_status_after_nack(*, retry_count: int, max_pull_retries: int) -> tuple[int, str]:
    next_retry = retry_count + 1
    if next_retry >= max_pull_retries:
        return next_retry, "dead"
    return next_retry, "new"


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

    async def count_pull_dead(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*)
                FROM pull_inbox
                WHERE status = 'dead'
                """
            )
            row = await cursor.fetchone()
            return row[0]

    async def pull_inbox_stats(self, *, bot_id: Optional[str] = None) -> Dict[str, int]:
        now = int(time.time())
        params: List[Any] = []
        where = ""
        if bot_id is not None:
            where = " WHERE bot_id = ?"
            params.append(bot_id)

        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                f"""
                SELECT
                    SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS new_count,
                    SUM(CASE WHEN status = 'leased' THEN 1 ELSE 0 END) AS leased_count,
                    SUM(CASE WHEN status = 'acked' THEN 1 ELSE 0 END) AS acked_count,
                    SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END) AS dead_count,
                    SUM(
                        CASE
                            WHEN status = 'leased' AND lease_until < ? THEN 1
                            ELSE 0
                        END
                    ) AS expired_leases
                FROM pull_inbox
                {where}
                """,
                (now, *params),
            )
            row = await cursor.fetchone()

        if row is None:
            return {
                "new_count": 0,
                "leased_count": 0,
                "acked_count": 0,
                "dead_count": 0,
                "expired_leases": 0,
            }

        return {
            "new_count": int(row[0] or 0),
            "leased_count": int(row[1] or 0),
            "acked_count": int(row[2] or 0),
            "dead_count": int(row[3] or 0),
            "expired_leases": int(row[4] or 0),
        }
        
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
                WHERE (status = 'new' OR (status = 'leased' AND lease_until < ?))
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

    async def ack_pull_batch(
        self,
        *,
        message_ids: List[int],
        consumer_id: str,
    ) -> Dict[str, Any]:
        unique_ids: List[int] = []
        seen = set()
        for message_id in message_ids:
            if message_id not in seen:
                unique_ids.append(message_id)
                seen.add(message_id)

        if not unique_ids:
            return {
                "acked_ids": [],
                "already_acked_ids": [],
                "rejected": [],
            }

        now = int(time.time())
        placeholders = ",".join("?" for _ in unique_ids)

        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"""
                SELECT id, status, consumer_id
                FROM pull_inbox
                WHERE id IN ({placeholders})
                """,
                tuple(unique_ids),
            )
            rows = await cursor.fetchall()
            found = {int(row[0]): {"status": row[1], "consumer_id": row[2]} for row in rows}

            ack_candidates: List[int] = []
            already_acked_ids: List[int] = []
            rejected: List[Dict[str, Any]] = []

            for message_id in unique_ids:
                row = found.get(message_id)
                if row is None:
                    rejected.append({"message_id": message_id, "reason": "not_found"})
                    continue

                status = row["status"]
                row_consumer_id = row["consumer_id"]

                if status == "acked":
                    already_acked_ids.append(message_id)
                elif status == "leased":
                    if row_consumer_id != consumer_id:
                        rejected.append({"message_id": message_id, "reason": "consumer_mismatch"})
                    else:
                        ack_candidates.append(message_id)
                elif status == "dead":
                    rejected.append({"message_id": message_id, "reason": "invalid_state_dead"})
                else:
                    rejected.append({"message_id": message_id, "reason": f"invalid_state_{status}"})

            if ack_candidates:
                ack_placeholders = ",".join("?" for _ in ack_candidates)
                await db.execute(
                    f"""
                    UPDATE pull_inbox
                    SET status = 'acked',
                        acked_at = ?,
                        lease_until = NULL
                    WHERE id IN ({ack_placeholders})
                      AND status = 'leased'
                      AND consumer_id = ?
                    """,
                    (now, *ack_candidates, consumer_id),
                )

            await db.commit()
            return {
                "acked_ids": ack_candidates,
                "already_acked_ids": already_acked_ids,
                "rejected": rejected,
            }

    async def nack_pull_batch(
        self,
        *,
        message_ids: List[int],
        consumer_id: str,
        error: Optional[str] = None,
        max_pull_retries: int = 5,
    ) -> Dict[str, Any]:
        unique_ids: List[int] = []
        seen = set()
        for message_id in message_ids:
            if message_id not in seen:
                unique_ids.append(message_id)
                seen.add(message_id)

        if not unique_ids:
            return {
                "requested": 0,
                "nacked": 0,
                "skipped": 0,
                "results": [],
            }

        placeholders = ",".join("?" for _ in unique_ids)

        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"""
                SELECT id, status, consumer_id, retry_count, bot_id, telegram_update_id
                FROM pull_inbox
                WHERE id IN ({placeholders})
                """,
                tuple(unique_ids),
            )
            rows = await cursor.fetchall()
            found = {
                int(row[0]): {
                    "status": row[1],
                    "consumer_id": row[2],
                    "retry_count": int(row[3]),
                    "bot_id": row[4],
                    "telegram_update_id": row[5],
                }
                for row in rows
            }

            to_new: List[Tuple[int, int]] = []
            to_dead: List[Tuple[int, int, str, int]] = []
            results: List[Dict[str, Any]] = []

            for message_id in unique_ids:
                row = found.get(message_id)
                if row is None:
                    results.append(
                        {"message_id": message_id, "status": "skipped", "reason": "not_found"}
                    )
                    continue

                status = row["status"]
                row_consumer_id = row["consumer_id"]

                if status != "leased":
                    results.append(
                        {
                            "message_id": message_id,
                            "status": "skipped",
                            "reason": f"invalid_state_{status}",
                        }
                    )
                    continue

                if row_consumer_id != consumer_id:
                    results.append(
                        {
                            "message_id": message_id,
                            "status": "skipped",
                            "reason": "consumer_mismatch",
                        }
                    )
                    continue

                next_retry, next_status = next_pull_status_after_nack(
                    retry_count=row["retry_count"],
                    max_pull_retries=max_pull_retries,
                )
                if next_status == "dead":
                    to_dead.append(
                        (
                            message_id,
                            next_retry,
                            str(row["bot_id"]),
                            int(row["telegram_update_id"]),
                        )
                    )
                else:
                    to_new.append((message_id, next_retry))

            if to_new:
                nack_placeholders = ",".join("?" for _ in to_new)
                new_ids = [item[0] for item in to_new]
                new_retries = [item[1] for item in to_new]
                if error is not None:
                    await db.execute(
                        f"""
                        UPDATE pull_inbox
                        SET status = 'new',
                            retry_count = CASE id {''.join(' WHEN ? THEN ?' for _ in to_new)} END,
                            consumer_id = NULL,
                            lease_until = NULL,
                            last_error = ?
                        WHERE id IN ({nack_placeholders})
                          AND status = 'leased'
                          AND consumer_id = ?
                        """,
                        (*[v for pair in zip(new_ids, new_retries) for v in pair], error, *new_ids, consumer_id),
                    )
                else:
                    await db.execute(
                        f"""
                        UPDATE pull_inbox
                        SET status = 'new',
                            retry_count = CASE id {''.join(' WHEN ? THEN ?' for _ in to_new)} END,
                            consumer_id = NULL,
                            lease_until = NULL
                        WHERE id IN ({nack_placeholders})
                          AND status = 'leased'
                          AND consumer_id = ?
                        """,
                        (*[v for pair in zip(new_ids, new_retries) for v in pair], *new_ids, consumer_id),
                    )

            if to_dead:
                dead_placeholders = ",".join("?" for _ in to_dead)
                dead_ids = [item[0] for item in to_dead]
                dead_retries = [item[1] for item in to_dead]
                if error is not None:
                    await db.execute(
                        f"""
                        UPDATE pull_inbox
                        SET status = 'dead',
                            retry_count = CASE id {''.join(' WHEN ? THEN ?' for _ in to_dead)} END,
                            consumer_id = NULL,
                            lease_until = NULL,
                            last_error = ?
                        WHERE id IN ({dead_placeholders})
                          AND status = 'leased'
                          AND consumer_id = ?
                        """,
                        (*[v for pair in zip(dead_ids, dead_retries) for v in pair], error, *dead_ids, consumer_id),
                    )
                else:
                    await db.execute(
                        f"""
                        UPDATE pull_inbox
                        SET status = 'dead',
                            retry_count = CASE id {''.join(' WHEN ? THEN ?' for _ in to_dead)} END,
                            consumer_id = NULL,
                            lease_until = NULL
                        WHERE id IN ({dead_placeholders})
                          AND status = 'leased'
                          AND consumer_id = ?
                        """,
                        (*[v for pair in zip(dead_ids, dead_retries) for v in pair], *dead_ids, consumer_id),
                    )

            await db.commit()

        for message_id, _, _, _ in to_dead:
            results.append({"message_id": message_id, "status": "nacked"})
        for message_id, _ in to_new:
            results.append({"message_id": message_id, "status": "nacked"})

        for message_id, retry_count, bot_id, telegram_update_id in to_dead:
            logger.warning(
                "pull message moved to dead: pull_message_id=%s bot_id=%s telegram_update_id=%s retry_count=%s last_error=%s",
                message_id,
                bot_id,
                telegram_update_id,
                retry_count,
                error,
            )

        results.sort(key=lambda item: item["message_id"])

        return {
            "requested": len(unique_ids),
            "nacked": len(to_new) + len(to_dead),
            "skipped": len(unique_ids) - len(to_new) - len(to_dead),
            "results": results,
        }
