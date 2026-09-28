from app.core.rate_limit import RateLimiter


def test_allows_up_to_the_limit_then_blocks() -> None:
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert [limiter.hit("ip", now=t) for t in (0, 1, 2)] == [None, None, None]
    wait = limiter.hit("ip", now=3)
    assert wait == 57  # the oldest hit (t=0) leaves the window at t=60


def test_window_slides() -> None:
    limiter = RateLimiter(limit=2, window_seconds=10)
    limiter.hit("ip", now=0)
    limiter.hit("ip", now=5)
    assert limiter.hit("ip", now=9) is not None
    assert limiter.hit("ip", now=10.5) is None  # t=0 expired


def test_keys_are_independent_and_retry_after_does_not_count() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.hit("a", now=0)
    assert limiter.retry_after("b", now=1) is None
    assert limiter.retry_after("b", now=1) is None  # peeking records nothing
    assert limiter.hit("b", now=1) is None
    assert limiter.hit("a", now=1) is not None


def test_reset() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.hit("ip", now=0)
    limiter.reset()
    assert limiter.hit("ip", now=1) is None
