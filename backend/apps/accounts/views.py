from firebase_admin import auth as firebase_auth
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.firebase import verify_id_token
from apps.accounts.models import User
from apps.accounts.serializers import FirebaseLoginSerializer, UserSerializer


class FirebaseLoginView(APIView):
    """Exchanges a verified Firebase ID token for a Django SimpleJWT pair."""

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
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)
