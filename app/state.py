from typing import Optional
from app.queue.sqlite import SQLiteQueue
import time

queue: Optional[SQLiteQueue] = None
started_at: float = time.time()
cleanup_last_run_at: float | None = None
cleanup_last_deleted_acked: int = 0
cleanup_last_deleted_dead: int = 0
cleanup_errors_total: int = 0
