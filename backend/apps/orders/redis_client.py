from functools import lru_cache

import redis
from django.conf import settings


@lru_cache(maxsize=1)
def get_redis():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def available_stock_key(product_id):
    return f"stock:avail:{product_id}"


def write_through_available(product_id, available):
    get_redis().set(available_stock_key(product_id), available)
