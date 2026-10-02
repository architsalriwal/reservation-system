from django.conf import settings
from firebase_admin import auth as firebase_auth
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.firebase import verify_id_token
from apps.accounts.models import User
from apps.accounts.serializers import FirebaseLoginSerializer, UserSerializer

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/auth/"


def _set_refresh_cookie(response, refresh_token):
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        str(refresh_token),
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Lax",
        path=REFRESH_COOKIE_PATH,
        max_age=int(refresh_token.lifetime.total_seconds()),
    )


class FirebaseLoginView(APIView):
    """FLOW STEP 2 (backend half): exchanges a verified Firebase ID token for
    a SimpleJWT pair. This is what frontend/src/services/auth.js's
    exchangeFirebaseToken() calls. By the time a request reaches here,
    Firebase has already confirmed the user's identity on the FRONTEND side
    (step 1) - this view's whole job is to independently re-verify that
    proof on the SERVER side (never trust a claim from the browser without
    checking it yourself) and then mint OUR OWN tokens.

    The access token goes in the JSON body (kept in memory by the frontend,
    never persisted, so it's not reachable by an XSS payload reading
    localStorage). The refresh token goes in an httpOnly cookie instead of
    the body, so JS on the page can never read it even if compromised.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = FirebaseLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # The actual cryptographic check happens in apps/accounts/firebase.py
        # - this call either returns the token's real, verified contents, or
        # raises, meaning the token was forged/tampered/expired.
        try:
            decoded = verify_id_token(serializer.validated_data["id_token"])
        except firebase_auth.InvalidIdTokenError:
            return Response({"detail": "Invalid Firebase ID token."}, status=401)
        except firebase_auth.ExpiredIdTokenError:
            return Response({"detail": "Firebase ID token has expired."}, status=401)

        firebase_uid = decoded["uid"]
        email = decoded.get("email", "")

        # First time this Firebase account has ever logged in to OUR app ->
        # create a matching local User row. Every later login just finds the
        # same row again via this same firebase_uid.
        user, _ = User.objects.get_or_create(
            firebase_uid=firebase_uid,
            defaults={"username": firebase_uid, "email": email},
        )
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])

        # This is where OUR tokens get created - nothing to do with Firebase
        # anymore from this point on. SimpleJWT mints a linked access+refresh
        # pair for this user.
        refresh = RefreshToken.for_user(user)
        response = Response({"access": str(refresh.access_token), "user": UserSerializer(user).data})
        _set_refresh_cookie(response, refresh)
        return response


class TokenRefreshView(APIView):
    """FLOW STEP 5 (backend half) and also what auth.js's restoreSession()
    (STEP 0) calls on page load. Called by frontend/src/services/api.js's
    response interceptor whenever an access token has expired (15 minutes
    after login, SIMPLE_JWT.ACCESS_TOKEN_LIFETIME). Note this view never
    looks at the request BODY for the refresh token - only the httpOnly
    cookie, which the browser attaches automatically and which JavaScript
    can never read or forge the content of.

    "Rotates" the refresh token: every time it's used, the OLD one is
    blacklisted (made permanently unusable, even if someone had copied it)
    and a brand NEW one is issued. This limits how long a stolen refresh
    token stays useful - using it once to refresh invalidates it, so an
    attacker who stole an old cookie and the real user both using it is a
    detectable, blockable collision instead of silent parallel access.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not raw_refresh:
            return Response({"detail": "No refresh cookie."}, status=401)

        try:
            refresh = RefreshToken(raw_refresh)
            access = refresh.access_token
            if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
                user = User.objects.get(pk=refresh["user_id"])
                if settings.SIMPLE_JWT.get("BLACKLIST_AFTER_ROTATION"):
                    refresh.blacklist()
                new_refresh = RefreshToken.for_user(user)
            else:
                new_refresh = refresh
        except (TokenError, User.DoesNotExist):
            return Response({"detail": "Invalid or expired refresh token."}, status=401)

        response = Response({"access": str(access)})
        _set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    """FLOW STEP 6 (backend half): called by auth.js's logout(). Blacklists
    the refresh token so it can never be used again (even though it hasn't
    expired yet), then deletes the cookie itself from the browser.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        raw_refresh = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass

        response = Response(status=204)
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
        return response


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)
