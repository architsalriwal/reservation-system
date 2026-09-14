from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.assistant.chat import run_chat
from apps.assistant.serializers import ChatRequestSerializer


class ChatView(APIView):
    """AllowAny, not IsAuthenticated: search and cart-adding both work for
    guests already (the cart is session-based), and get_order_status simply
    reports it needs a login rather than blocking the whole conversation.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = run_chat(
            message=serializer.validated_data["message"],
            history=serializer.validated_data["history"],
            user=request.user,
            session=request.session,
        )
        return Response(result)
