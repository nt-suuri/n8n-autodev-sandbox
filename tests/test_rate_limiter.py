import sqlite3
import threading
import time
from pathlib import Path

import pytest

from sandbox.rate_limiter import RateLimiter, RateLimitExceeded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_limiter(tmp_path: Path, *, capacity: int = 5, refill: float = 1.0) -> RateLimiter:
    return RateLimiter(
        name="test",
        capacity=capacity,
        refill_per_second=refill,
        db_path=tmp_path / "rl.db",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_acquire_context_manager(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path)
    entered = False
    with limiter.acquire("op"):
        entered = True
    assert entered


def test_decorator_returns_wrapped_result(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path)

    @limiter.limit("op")
    def compute(x: int) -> int:
        return x * 2

    assert compute(21) == 42


def test_multiple_keys_are_independent(tmp_path: Path) -> None:
    limiter = RateLimiter("test", capacity=1, refill_per_second=0.001, db_path=tmp_path / "rl.db")
    with limiter.acquire("key_a"):
        pass
    with limiter.acquire("key_b"):  # separate bucket, should not be affected
        pass


# ---------------------------------------------------------------------------
# Exhaustion
# ---------------------------------------------------------------------------


def test_exhaustion_raises_rate_limit_exceeded(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path, capacity=2, refill=0.001)
    with limiter.acquire("op"):
        pass
    with limiter.acquire("op"):
        pass

    with pytest.raises(RateLimitExceeded) as exc_info:
        with limiter.acquire("op"):
            pass

    assert exc_info.value.retry_after_seconds > 0.0


def test_rate_limit_exceeded_retry_after_is_sensible(tmp_path: Path) -> None:
    limiter = RateLimiter("test", capacity=1, refill_per_second=1.0, db_path=tmp_path / "rl.db")
    with limiter.acquire("op"):
        pass

    with pytest.raises(RateLimitExceeded) as exc_info:
        with limiter.acquire("op"):
            pass

    assert 0.0 < exc_info.value.retry_after_seconds <= 1.0


def test_decorator_raises_rate_limit_exceeded(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path, capacity=1, refill=0.001)

    @limiter.limit("op")
    def fn() -> int:
        return 1

    assert fn() == 1
    with pytest.raises(RateLimitExceeded):
        fn()


# ---------------------------------------------------------------------------
# Refill after wait
# ---------------------------------------------------------------------------


def test_refill_after_wait(tmp_path: Path) -> None:
    # 4 tokens/sec → 1 token refills in 250 ms; sleep 300 ms to be safe
    limiter = RateLimiter("test", capacity=1, refill_per_second=4.0, db_path=tmp_path / "rl.db")

    with limiter.acquire("op"):
        pass

    # Bucket is now at 0; immediate second call must fail (< 250 ms has elapsed)
    with pytest.raises(RateLimitExceeded):
        with limiter.acquire("op"):
            pass

    time.sleep(0.30)  # wait past 250 ms refill window

    with limiter.acquire("op"):  # must succeed after refill
        pass


# ---------------------------------------------------------------------------
# Acquire with timeout
# ---------------------------------------------------------------------------


def test_acquire_with_timeout_waits_for_refill(tmp_path: Path) -> None:
    # 4 tokens/sec → 1 token refills in 250 ms; timeout=0.4s guarantees the wait-loop runs
    limiter = RateLimiter("test", capacity=1, refill_per_second=4.0, db_path=tmp_path / "rl.db")
    with limiter.acquire("op"):
        pass

    with limiter.acquire("op", timeout=0.4):
        pass  # must block inside the retry loop until the token refills


def test_acquire_timeout_exceeded_raises(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path, capacity=1, refill=0.001)
    with limiter.acquire("op"):
        pass

    with pytest.raises(RateLimitExceeded):
        with limiter.acquire("op", timeout=0.05):
            pass


def test_acquire_zero_timeout_raises_immediately_when_empty(tmp_path: Path) -> None:
    limiter = make_limiter(tmp_path, capacity=1, refill=0.001)
    with limiter.acquire("op"):
        pass

    with pytest.raises(RateLimitExceeded):
        with limiter.acquire("op", timeout=0.0):
            pass


# ---------------------------------------------------------------------------
# Concurrent safety
# ---------------------------------------------------------------------------


def test_concurrent_acquire_does_not_over_consume(tmp_path: Path) -> None:
    capacity = 3
    num_threads = 8
    limiter = RateLimiter(
        "concurrent",
        capacity=capacity,
        refill_per_second=0.001,  # negligible refill during test
        db_path=tmp_path / "rl.db",
    )

    successes: list[int] = []
    failures: list[int] = []
    barrier = threading.Barrier(num_threads)

    def try_acquire() -> None:
        barrier.wait()
        try:
            with limiter.acquire("op"):
                successes.append(1)
        except RateLimitExceeded:
            failures.append(1)

    threads = [threading.Thread(target=try_acquire) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert len(successes) == capacity
    assert len(successes) + len(failures) == num_threads


# ---------------------------------------------------------------------------
# Restart recovery (state survives process restart)
# ---------------------------------------------------------------------------


def test_state_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "rl.db"
    limiter = RateLimiter("persistent", capacity=2, refill_per_second=0.001, db_path=db_path)
    with limiter.acquire("op"):
        pass
    with limiter.acquire("op"):
        pass
    del limiter  # simulate process end

    limiter2 = RateLimiter("persistent", capacity=2, refill_per_second=0.001, db_path=db_path)
    with pytest.raises(RateLimitExceeded):
        with limiter2.acquire("op"):
            pass


# ---------------------------------------------------------------------------
# Invalid inputs
# ---------------------------------------------------------------------------


def test_invalid_capacity_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="capacity"):
        RateLimiter("t", capacity=0, refill_per_second=1.0, db_path=tmp_path / "rl.db")


def test_invalid_capacity_negative(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="capacity"):
        RateLimiter("t", capacity=-1, refill_per_second=1.0, db_path=tmp_path / "rl.db")


def test_invalid_refill_zero(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refill_per_second"):
        RateLimiter("t", capacity=1, refill_per_second=0.0, db_path=tmp_path / "rl.db")


def test_invalid_refill_negative(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refill_per_second"):
        RateLimiter("t", capacity=1, refill_per_second=-1.0, db_path=tmp_path / "rl.db")


def test_invalid_db_path_parent_missing() -> None:
    with pytest.raises(ValueError, match="parent directory"):
        RateLimiter("t", capacity=1, refill_per_second=1.0, db_path="/nonexistent/deep/path/rl.db")


def test_db_path_as_string(tmp_path: Path) -> None:
    limiter = RateLimiter("t", capacity=1, refill_per_second=1.0, db_path=str(tmp_path / "rl.db"))
    with limiter.acquire("op"):
        pass


# ---------------------------------------------------------------------------
# Error path: SQLite failure propagates
# ---------------------------------------------------------------------------


def test_sqlite_error_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = make_limiter(tmp_path)

    def failing_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError("disk full")

    import sandbox.rate_limiter as module

    monkeypatch.setattr(module.sqlite3, "connect", failing_connect)

    with pytest.raises(sqlite3.OperationalError, match="disk full"):
        with limiter.acquire("op"):
            pass
