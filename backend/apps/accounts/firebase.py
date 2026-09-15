import threading

import firebase_admin
from django.conf import settings
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

_app = None
_app_lock = threading.Lock()


def get_firebase_app():
    """Lazily initializes the Firebase Admin app from the configured credentials path.

    Deliberately a single function reading a single settings value, unlike the
    previous project where the settings path and the path actually used by the
    auth code had silently diverged.

    Daphne/gunicorn can serve more than one request concurrently on the same
    worker (threads, or async handlers), so the first few logins after a cold
    start can call this at the same time. A bare "if _app is None" check-then-
    act here is exactly the kind of race this project exists to get right
    elsewhere - two threads can both see None and both call initialize_app(),
    and the second one raises. Double-checked locking closes that window: the
    lock is only ever taken during that brief cold-start race, never on the
    steady-state fast path once _app is set.
    """
    global _app
    if _app is not None:
        return _app

    with _app_lock:
        if _app is not None:
            return _app

        if not settings.FIREBASE_CREDENTIALS_PATH:
            raise RuntimeError(
                "FIREBASE_CREDENTIALS_PATH is not set. Provide it via the FIREBASE_CREDENTIALS_PATH "
                "env var, pointing at a service-account JSON that is never committed to git."
            )

        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        _app = firebase_admin.initialize_app(cred)
        return _app


def verify_id_token(id_token):
    """Verifies a Firebase ID token and returns its decoded claims.

    Raises firebase_admin.auth.InvalidIdTokenError (or a subclass) on failure —
    callers should let that propagate into a 401, not swallow it silently.

    clock_skew_seconds gives a small amount of leeway on the token's "issued
    at" claim. Without it, a token minted by Google's servers and verified
    here milliseconds later can get rejected as "used too early" whenever
    this machine's clock lags Google's by even a second or two - a normal,
    expected amount of drift, not a sign the token is actually invalid.
    """
    get_firebase_app()
    return firebase_auth.verify_id_token(id_token, clock_skew_seconds=10)
