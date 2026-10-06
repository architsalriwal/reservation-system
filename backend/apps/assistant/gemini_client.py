# The single shared connection to Google's Gemini API - every other file
# in this app (chat.py, embeddings.py) goes through get_client() below
# instead of each creating its own separate connection.

from functools import lru_cache

from django.conf import settings
from google import genai


# @lru_cache(maxsize=1): run this function's body only ONCE, ever, no
# matter how many times get_client() gets called - every caller after the
# first just receives the same already-built client object back instantly,
# instead of reconnecting from scratch each time. Same pattern as
# apps/orders/redis_client.py's get_redis().
@lru_cache(maxsize=1)
def get_client():
    if not settings.GEMINI_API_KEY:
        # Fail loudly and immediately with a clear message, rather than
        # letting a missing API key cause a confusing error buried deep
        # inside Google's own client library later.
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Provide it via the GEMINI_API_KEY env var."
        )
    return genai.Client(api_key=settings.GEMINI_API_KEY)
