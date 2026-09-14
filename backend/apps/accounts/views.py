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
    """Exchanges a verified Firebase ID token for a SimpleJWT pair.

    The access token goes in the JSON body (kept in memory by the frontend,
    never persisted, so it's not reachable by an XSS payload reading
    localStorage). The refresh token goes in an httpOnly cookie instead of
    the body, so JS on the page can never read it even if compromised.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = FirebaseLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            decoded = verify_id_token(serializer.validated_data["id_token"])
        except firebase_auth.InvalidIdTokenError:
            return Response({"detail": "Invalid Firebase ID token."}, status=401)
        except firebase_auth.ExpiredIdTokenError:
            return Response({"detail": "Firebase ID token has expired."}, status=401)

        firebase_uid = decoded["uid"]
        email = decoded.get("email", "")

        user, _ = User.objects.get_or_create(
            firebase_uid=firebase_uid,
            defaults={"username": firebase_uid, "email": email},
        )
        if email and user.email != email:
            user.email = email
            user.save(update_fields=["email"])

        refresh = RefreshToken.for_user(user)
        response = Response({"access": str(refresh.access_token), "user": UserSerializer(user).data})
        _set_refresh_cookie(response, refresh)
        return response


class TokenRefreshView(APIView):
    """Reads the refresh token from the httpOnly cookie (never the body),
    rotates it, and returns a fresh access token plus the new cookie.
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
