import httpx
import pytest

from app.resilience import CircuitOpen, call_with_retry, reset_breakers


@pytest.fixture(autouse=True)
def _reset():
    reset_breakers()


def status_error(code):
    req = httpx.Request("GET", "http://x")
    return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))


def counting(exc):
    calls = []

    def fn():
        calls.append(1)
        raise exc

    return fn, calls


@pytest.mark.parametrize("code", [429, 503])
def test_retried_twice_then_raised(code):
    fn, calls = counting(status_error(code))
    sleeps = []
    with pytest.raises(httpx.HTTPStatusError):
        call_with_retry(fn, api="a", sleep=sleeps.append)
    assert len(calls) == 3 and len(sleeps) == 2 and sleeps[1] > sleeps[0] * 1.0


def test_400_and_value_error_not_retried():
    for exc in (status_error(400), ValueError("schema")):
        fn, calls = counting(exc)
        with pytest.raises(type(exc)):
            call_with_retry(fn, api="a", sleep=lambda s: None)
        assert len(calls) == 1


def test_timeout_retried_and_success_returns():
    seq = [httpx.ReadTimeout("t"), "ok"]

    def fn():
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    assert call_with_retry(fn, api="a", sleep=lambda s: None) == "ok"


def test_google_style_code_attribute_retried():
    class APIError(Exception):
        code = 503

    fn, calls = counting(APIError())
    with pytest.raises(APIError):
        call_with_retry(fn, api="a", sleep=lambda s: None)
    assert len(calls) == 3


def test_breaker_opens_then_recovers_after_cooldown():
    now = [100.0]
    clock = lambda: now[0]
    fn, calls = counting(status_error(503))
    for _ in range(3):
        with pytest.raises(httpx.HTTPStatusError):
            call_with_retry(fn, api="a", retries=0, sleep=lambda s: None, clock=clock)
    with pytest.raises(CircuitOpen):
        call_with_retry(fn, api="a", retries=0, clock=clock)
    assert len(calls) == 3
    other = call_with_retry(lambda: "fine", api="b", clock=clock)
    assert other == "fine"
    now[0] += 31
    assert call_with_retry(lambda: "back", api="a", clock=clock) == "back"
    assert call_with_retry(lambda: "again", api="a", clock=clock) == "again"
