import pytest
from starlette.requests import Request

from app.core.rate_limit import RateLimiter, client_ip


def request_with(*forwarded_for: str, peer: str = "169.254.1.1") -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded_for]
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.mark.parametrize(
    ("forwarded_for", "expected"),
    [
        (("81.214.10.7",), "81.214.10.7"),
        # A visitor's own header comes first; Cloud Run appends the address it saw.
        (("1.2.3.4, 81.214.10.7",), "81.214.10.7"),
        (("1.2.3.4", "81.214.10.7"), "81.214.10.7"),  # the same header sent twice
        (("not-an-ip, 81.214.10.7",), "81.214.10.7"),
        # Google's front ends and internal hops after it are skipped.
        (("1.2.3.4, 81.214.10.7, 35.191.5.6",), "81.214.10.7"),
        (("81.214.10.7, 10.0.0.2",), "81.214.10.7"),
        (("1.2.3.4, 2001:db8::1, 2a00:1450::5",), "2a00:1450::5"),
        ((), "169.254.1.1"),  # no proxy (local runs): the connection's address
        (("10.0.0.2",), "169.254.1.1"),
    ],
)
def test_the_client_address_comes_from_the_right(forwarded_for: tuple[str, ...], expected: str) -> None:
    assert client_ip(request_with(*forwarded_for)) == expected


def test_made_up_addresses_do_not_get_around_a_limit() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60)
    hits = [limiter.hit(client_ip(request_with(f"9.9.9.{i}, 81.214.10.7")), now=i) for i in range(3)]
    assert hits[:2] == [None, None] and hits[2] is not None


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
