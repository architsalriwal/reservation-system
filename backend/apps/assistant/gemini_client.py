from functools import lru_cache

from django.conf import settings
from google import genai


@lru_cache(maxsize=1)
def get_client():
    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Provide it via the GEMINI_API_KEY env var."
        )
    return genai.Client(api_key=settings.GEMINI_API_KEY)
