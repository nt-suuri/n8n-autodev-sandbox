import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

_DB_TIMEOUT_SECONDS: float = 5.0
_RETRY_INTERVAL_SECONDS: float = 0.05

P = ParamSpec("P")
T = TypeVar("T")


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded; retry after {retry_after_seconds:.3f}s")


class RateLimiter:
    def __init__(
        self,
        name: str,
        capacity: int,
        refill_per_second: float,
        db_path: str | Path,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f"capacity must be > 0, got {capacity}")
        if refill_per_second <= 0.0:
            raise ValueError(f"refill_per_second must be > 0, got {refill_per_second}")
        db_path = Path(db_path)
        if not db_path.parent.exists():
            raise ValueError(f"db_path parent directory does not exist: {db_path.parent}")

        self._name = name
        self._capacity = capacity
        self._refill_per_second = refill_per_second
        self._db_path = db_path
        # Maps full_key → (wall_at_write, mono_at_write) for same-process elapsed tracking.
        self._mono_anchors: dict[str, tuple[float, float]] = {}
        self._anchors_lock = threading.Lock()

        self._init_db()
        logger.info(
            "RateLimiter ready: name=%s capacity=%d refill_per_second=%s db=%s",
            name,
            capacity,
            refill_per_second,
            db_path,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=_DB_TIMEOUT_SECONDS,
            check_same_thread=False,
            isolation_level=None,  # autocommit; transactions managed explicitly
        )
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS buckets (
                    key TEXT PRIMARY KEY,
                    tokens REAL NOT NULL,
                    last_refill_at REAL NOT NULL
                )
                """
            )
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _try_consume(self, conn: sqlite3.Connection, key: str) -> float | None:
        now_wall = time.time()
        now_mono = time.monotonic()

        row = conn.execute(
            "SELECT tokens, last_refill_at FROM buckets WHERE key = ?", (key,)
        ).fetchone()

        if row is None:
            tokens: float = float(self._capacity)
        else:
            stored_tokens, last_refill_at = row

            with self._anchors_lock:
                anchor = self._mono_anchors.get(key)

            if anchor is not None and anchor[0] == last_refill_at:
                # This process wrote last_refill_at — use monotonic to avoid NTP jumps.
                elapsed = max(0.0, now_mono - anchor[1])
            else:
                # Cross-process write or first access: wall-clock is the only reference.
                elapsed = max(0.0, now_wall - last_refill_at)

            tokens = min(float(self._capacity), stored_tokens + elapsed * self._refill_per_second)

        if tokens >= 1.0:
            conn.execute(
                """
                INSERT INTO buckets (key, tokens, last_refill_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    tokens = excluded.tokens,
                    last_refill_at = excluded.last_refill_at
                """,
                (key, tokens - 1.0, now_wall),
            )
            with self._anchors_lock:
                self._mono_anchors[key] = (now_wall, now_mono)
            logger.debug("Consumed token for %s; remaining=%.3f", key, tokens - 1.0)
            return None

        retry_after = (1.0 - tokens) / self._refill_per_second
        logger.debug("Bucket empty for %s; retry_after=%.3f", key, retry_after)
        return retry_after

    def _acquire_once(self, key: str) -> float | None:
        """
        Opens a fresh connection and attempts one atomic token acquisition.
        BEGIN IMMEDIATE serialises concurrent writers across threads and processes.
        """
        full_key = f"{self._name}:{key}"
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = self._try_consume(conn, full_key)
            conn.execute("COMMIT")
            return result
        except sqlite3.Error:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()

    @contextmanager
    def acquire(self, key: str, timeout: float | None = None) -> Generator[None, None, None]:
        """
        Acquires one token, waiting up to `timeout` seconds if set.
        Raises RateLimitExceeded immediately when timeout is None and bucket is empty.
        """
        deadline = time.monotonic() + timeout if timeout is not None else None

        while True:
            retry_after = self._acquire_once(key)
            if retry_after is None:
                logger.info("Token acquired: %s/%s", self._name, key)
                yield
                return

            if deadline is None:
                raise RateLimitExceeded(retry_after_seconds=retry_after)

            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise RateLimitExceeded(retry_after_seconds=retry_after)

            time.sleep(min(_RETRY_INTERVAL_SECONDS, remaining))

    def limit(self, key: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
        """Returns a decorator that consumes one token per call, raising RateLimitExceeded when empty."""

        def decorator(fn: Callable[P, T]) -> Callable[P, T]:
            @wraps(fn)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
                with self.acquire(key):
                    return fn(*args, **kwargs)

            return wrapper

        return decorator
