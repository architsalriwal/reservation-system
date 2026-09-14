from rest_framework import serializers


class ChatTurnSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "model"])
    text = serializers.CharField()


class ChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    history = ChatTurnSerializer(many=True, required=False, default=list)
