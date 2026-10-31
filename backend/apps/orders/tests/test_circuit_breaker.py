# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# A circuit breaker has three states, like an actual electrical circuit
# breaker in your house:
#   CLOSED    - normal operation, calls go through as usual.
#   OPEN      - too many recent failures; calls are rejected IMMEDIATELY,
#               without even attempting them, so a struggling dependency
#               (e.g. Stripe being down) doesn't get hammered further.
#   HALF-OPEN - after a cooldown period, let exactly ONE "probe" call
#               through to test if the dependency has recovered. If it
#               succeeds, go back to CLOSED. If it fails, go back to OPEN.
#
# These tests walk through that whole state machine in order: closed and
# working, closed but under the failure threshold, tripping into open,
# transitioning to half-open after the cooldown, a successful probe
# resetting everything, a failed probe reopening it, and finally the
# trickiest case - making sure that if several requests arrive at the exact
# moment the breaker goes half-open, only ONE of them gets to be "the
# probe" and the rest are still rejected (otherwise you'd hammer the
# recovering dependency with every request that arrived in that window).
# ============================================================================

"""Proof that this is a real circuit breaker (closed/open/half-open with a
cooldown and a single test probe) and not just a try/except with a timeout.
The difference that actually matters: once open, it must reject calls
WITHOUT even attempting them - a plain try/except still tries every time.
"""

from unittest.mock import patch

import pytest

from apps.orders.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


def _breaker(**kwargs):
    # A shared helper so every test below gets an identically-configured
    # breaker: trips after 3 failures, then waits 30 simulated seconds
    # before allowing a recovery probe.
    return CircuitBreaker("test-breaker", failure_threshold=3, cooldown_seconds=30, **kwargs)


def test_closed_breaker_lets_calls_through_and_returns_the_result():
    breaker = _breaker()
    result = breaker.call(lambda: "ok")
    assert result == "ok"


def test_breaker_opens_after_reaching_the_failure_threshold():
    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731

    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    # The 4th call must be rejected WITHOUT ever calling failing_fn again -
    # that's the actual point of a circuit breaker over plain error handling.
    with patch("apps.orders.tests.test_circuit_breaker._never_called") as spy:
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(spy)
        spy.assert_not_called()


def _never_called():
    raise AssertionError("should never be invoked while the breaker is open")


def test_breaker_stays_closed_below_the_failure_threshold():
    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731

    for _ in range(2):  # one under the threshold of 3
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    # Still closed - a call that succeeds should go through normally.
    assert breaker.call(lambda: "ok") == "ok"


def test_open_breaker_moves_to_half_open_after_the_cooldown_and_allows_one_probe():
    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    with pytest.raises(CircuitBreakerOpen):
        breaker.call(lambda: "should not run")

    # Faking time.time() to return a value 31 seconds in the future is how
    # this test crosses the 30-second cooldown instantly, instead of
    # actually calling time.sleep(31) and making the test suite slow.
    with patch("apps.orders.circuit_breaker.time.time", return_value=__import__("time").time() + 31):
        # Past the 30s cooldown - the probe should be allowed through.
        result = breaker.call(lambda: "healthy again")

    assert result == "healthy again"


def test_successful_probe_closes_the_breaker_and_resets_failure_count():
    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    with patch("apps.orders.circuit_breaker.time.time", return_value=__import__("time").time() + 31):
        breaker.call(lambda: "healthy")

    # Fully reset now: back-to-back calls should work with no special state.
    assert breaker.call(lambda: "still healthy") == "still healthy"


def test_failed_probe_reopens_the_breaker_with_a_fresh_cooldown():
    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    real_time = __import__("time").time()
    with patch("apps.orders.circuit_breaker.time.time", return_value=real_time + 31):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)  # the probe itself fails

    # Immediately after the failed probe, at the SAME point in time, the
    # breaker must already be open again - not still half-open.
    with patch("apps.orders.circuit_breaker.time.time", return_value=real_time + 31):
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(lambda: "should not run")


def test_concurrent_requests_during_half_open_only_let_one_probe_through():
    """The Redis SET NX claim is what makes this safe under real concurrency
    - without it, every request arriving right after the cooldown would
    simultaneously hammer a dependency that isn't confirmed healthy yet.
    """
    import threading
    import time as time_module

    breaker = _breaker()
    failing_fn = lambda: (_ for _ in ()).throw(RuntimeError("down"))  # noqa: E731
    for _ in range(3):
        with pytest.raises(RuntimeError):
            breaker.call(failing_fn)

    started = threading.Event()
    release = threading.Event()
    calls = []

    def slow_probe():
        calls.append(1)
        started.set()
        release.wait(timeout=5)  # stays "in flight" until the test lets it finish
        return "ok"

    results = {}

    def run_first():
        results["first"] = breaker.call(slow_probe)

    real_time = time_module.time()
    with patch("apps.orders.circuit_breaker.time.time", return_value=real_time + 31):
        first_thread = threading.Thread(target=run_first)
        first_thread.start()
        started.wait(timeout=5)  # the first call has claimed the probe slot but not finished yet

        # A second request arrives while the first probe is still in flight -
        # it must be rejected, not allowed to also hit the dependency.
        with pytest.raises(CircuitBreakerOpen):
            breaker.call(lambda: "should not run")

        release.set()
        first_thread.join(timeout=5)

    assert results["first"] == "ok"
    assert len(calls) == 1
