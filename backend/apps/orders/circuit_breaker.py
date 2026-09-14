"""A real circuit breaker (closed / open / half-open), not just a
try/except with a timeout.

State lives in Redis, not in a Python variable on the class - Django and
Celery run as several separate processes (gunicorn workers, a Celery
worker, ...), and a breaker whose memory resets every time a new process
starts, or that only one of several processes knows about, isn't actually
protecting anything. Redis gives every process the same shared view of
"is this dependency currently healthy".

States:
- CLOSED (normal): calls go through; each failure is counted.
- OPEN (tripped): calls are rejected immediately, without even attempting
  them, until the cooldown passes. This is the actual point of a circuit
  breaker over plain error handling - during an outage, the app stops
  wasting time on requests that were almost certainly going to fail anyway.
- HALF_OPEN (probing): once the cooldown passes, exactly one caller is let
  through as a test. Success closes the breaker and resets the failure
  count; failure re-opens it with a fresh cooldown.
"""

import time

from apps.orders.redis_client import get_redis


class CircuitBreakerOpen(Exception):
    """Raised instead of even attempting the wrapped call."""


class CircuitBreaker:
    def __init__(self, name, failure_threshold=5, cooldown_seconds=30):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def _key(self, suffix):
        return f"circuit_breaker:{self.name}:{suffix}"

    def _state(self):
        opened_at = get_redis().get(self._key("opened_at"))
        if opened_at is None:
            return "closed"
        if time.time() - float(opened_at) >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def call(self, fn, *args, **kwargs):
        state = self._state()

        if state == "open":
            raise CircuitBreakerOpen(f"{self.name} circuit is open - not attempting the call.")

        if state == "half_open":
            # Claim the single probe slot atomically (SET NX) so concurrent
            # requests during half-open don't all pile onto a dependency
            # that isn't confirmed healthy yet - only one gets through,
            # everyone else still fails fast.
            claimed = get_redis().set(self._key("probing"), "1", nx=True, ex=self.cooldown_seconds)
            if not claimed:
                raise CircuitBreakerOpen(f"{self.name} circuit is half-open - a probe is already in flight.")

        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._record_failure(state)
            raise
        else:
            self._record_success()
            return result

    def _record_success(self):
        get_redis().delete(self._key("opened_at"), self._key("failures"), self._key("probing"))

    def _record_failure(self, state_before_call):
        redis_conn = get_redis()
        if state_before_call == "half_open":
            # The probe failed - straight back to open, no need to recount
            # failures from scratch.
            redis_conn.set(self._key("opened_at"), time.time())
            redis_conn.delete(self._key("probing"))
            return

        failures = redis_conn.incr(self._key("failures"))
        redis_conn.expire(self._key("failures"), self.cooldown_seconds * 4)
        if failures >= self.failure_threshold:
            redis_conn.set(self._key("opened_at"), time.time())
