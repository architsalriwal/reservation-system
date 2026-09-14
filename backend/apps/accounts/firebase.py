import firebase_admin
from django.conf import settings
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

_app = None


def get_firebase_app():
    """Lazily initializes the Firebase Admin app from the configured credentials path.

    Deliberately a single function reading a single settings value, unlike the
    previous project where the settings path and the path actually used by the
    auth code had silently diverged.
    """
    global _app
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
    """
    get_firebase_app()
    return firebase_auth.verify_id_token(id_token)
