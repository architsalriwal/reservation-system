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

BEGINNER NOTE: the only place this is actually used (right now) is
apps/orders/views.py's CheckoutView, wrapping the call to Stripe. Think of
it like your house's fuse box: if an appliance keeps tripping the circuit,
the fuse box stops sending power down that line for a while instead of
letting every device on it keep drawing power through a known problem.
Here, "the appliance" is Stripe, and "stops sending power" means "stop even
trying to call Stripe for 30 seconds."
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
        # Builds the Redis key name this breaker's state lives under, e.g.
        # "circuit_breaker:stripe:opened_at". A leading underscore on a
        # method name (_key, _state, _record_success...) is just a Python
        # convention meaning "internal helper, not meant to be called from
        # outside this class" - it's not enforced by the language, just a
        # signal to other developers.
        return f"circuit_breaker:{self.name}:{suffix}"

    def _state(self):
        # "opened_at" is only ever SET when the breaker trips open (see
        # _record_failure below) - if it's missing from Redis entirely,
        # the breaker has never tripped (or was reset by a success), so
        # we're in the normal CLOSED state.
        opened_at = get_redis().get(self._key("opened_at"))
        if opened_at is None:
            return "closed"
        # It tripped open at some point - has enough time passed since then
        # to allow one test call through?
        if time.time() - float(opened_at) >= self.cooldown_seconds:
            return "half_open"
        return "open"

    def call(self, fn, *args, **kwargs):
        """Runs `fn(*args, **kwargs)` through the breaker instead of calling
        it directly. `fn` here is literally a function passed in as an
        argument (e.g. stripe.checkout.Session.create) - this is Python
        treating functions as ordinary values you can pass around, not
        special syntax specific to this file.
        """
        state = self._state()

        if state == "open":
            # Don't even attempt the real call - this is the entire point
            # of a circuit breaker versus a plain try/except: a plain
            # try/except still calls Stripe on every single request, even
            # during a known outage, wasting time waiting for a failure
            # that's nearly certain.
            raise CircuitBreakerOpen(f"{self.name} circuit is open - not attempting the call.")

        if state == "half_open":
            # Claim the single probe slot atomically (SET NX) so concurrent
            # requests during half-open don't all pile onto a dependency
            # that isn't confirmed healthy yet - only one gets through,
            # everyone else still fails fast.
            #
            # nx=True means "SET this value only if the key doesn't already
            # exist." If 10 requests arrive during this half-open window,
            # only the FIRST one to reach Redis gets `claimed = True` - every
            # other one gets `claimed = False` (the key already existed) and
            # is rejected below, without ever touching Stripe.
            claimed = get_redis().set(self._key("probing"), "1", nx=True, ex=self.cooldown_seconds)
            if not claimed:
                raise CircuitBreakerOpen(f"{self.name} circuit is half-open - a probe is already in flight.")

        try:
            # This is the ONE moment the real call (e.g. the actual network
            # request to Stripe) happens - everything above was just
            # deciding whether we're even allowed to get here.
            result = fn(*args, **kwargs)
        except Exception:
            self._record_failure(state)
            # `raise` with nothing after it re-raises the SAME exception
            # that was just caught, after we're done recording it - the
            # caller (CheckoutView) still sees the real error and handles
            # it, this class just also quietly updates the failure count
            # on the way past.
            raise
        else:
            self._record_success()
            return result

    def _record_success(self):
        # A successful call means the dependency is healthy again - wipe
        # every trace of past trouble (failure count, open/probing state)
        # so the breaker is back to a totally clean CLOSED state.
        get_redis().delete(self._key("opened_at"), self._key("failures"), self._key("probing"))

    def _record_failure(self, state_before_call):
        redis_conn = get_redis()
        if state_before_call == "half_open":
            # The probe failed - straight back to open, no need to recount
            # failures from scratch.
            redis_conn.set(self._key("opened_at"), time.time())
            redis_conn.delete(self._key("probing"))
            return

        # redis_conn.incr(...) atomically adds 1 to a counter stored in
        # Redis and returns the new total - this is itself safe even if
        # many requests fail at the exact same instant, since Redis
        # processes each command one at a time internally.
        failures = redis_conn.incr(self._key("failures"))
        redis_conn.expire(self._key("failures"), self.cooldown_seconds * 4)
        if failures >= self.failure_threshold:
            # Hit the limit (5 by default) - trip the breaker open.
            redis_conn.set(self._key("opened_at"), time.time())
