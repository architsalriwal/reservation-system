# This whole file is small on purpose: Redis is only ever used here as a
# fast, "good enough" CACHE of stock counts - never as the real source of
# truth. Postgres (see services.py's row lock) is the only thing that
# actually decides who gets the last unit of something. If this Redis cache
# were wiped completely, nothing would break - checkout would just get a
# little slower until it refills itself.

from functools import lru_cache

import redis
from django.conf import settings


# @lru_cache(maxsize=1) means: run this function's body only ONCE, ever, and
# just hand back the same saved result every time after that. In plain
# words - "build one Redis connection the first time anyone needs it, then
# reuse that same connection forever instead of opening a new one on every
# single call."
@lru_cache(maxsize=1)
def get_redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


# Redis is just a giant dictionary of text-key -> value. This function
# builds the exact key name we use for "how many of product X are
# available right now?" - e.g. product id 7 -> the key "stock:avail:7".
# Having one function build this string means every other file asking for
# or writing this value spells the key exactly the same way, with no risk
# of a typo creating a second, different key by accident.
def available_stock_key(product_id):
    return f"stock:avail:{product_id}"


# "Write-through" just means: after Postgres (the real database) has
# finished changing a product's real stock count, immediately copy that
# new, correct number into Redis too, so the next person's cheap pre-check
# (see begin_checkout in services.py) sees an up-to-date number instead of
# a stale one.
def write_through_available(product_id, available):
    get_redis().set(available_stock_key(product_id), available)
