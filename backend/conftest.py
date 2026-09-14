import pytest

from apps.orders.redis_client import get_redis


@pytest.fixture(autouse=True)
def flush_redis():
    """Redis isn't reset between tests the way the DB transaction is, and
    Postgres sequences do reset after a TransactionTestCase-style truncation
    — so a stale stock:avail:<id> key from an earlier test can collide with
    a freshly created product that reuses the same id. Flush before each
    test so the availability pre-check cache never leaks across tests.
    """
    get_redis().flushdb()
    yield
