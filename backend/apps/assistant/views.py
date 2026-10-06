# The actual HTTP endpoint the frontend's chat widget talks to
# (POST /api/assistant/chat/) - this file is intentionally tiny. All the
# real logic (the AI conversation loop, tool calling) lives in chat.py;
# this view's only job is translating one web request into one run_chat()
# call and sending back whatever it returns as JSON.

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

        # `request.user` here might be an anonymous (not-logged-in) user -
        # that's fine and expected. It gets passed straight through into
        # run_chat()'s tool_context, and apps/assistant/tools.py's
        # _get_order_status is the one tool that actually checks
        # `user.is_authenticated` and refuses if it's false.
        result = run_chat(
            message=serializer.validated_data["message"],
            history=serializer.validated_data["history"],
            user=request.user,
            session=request.session,
        )
        return Response(result)
