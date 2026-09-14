import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView

from apps.orders.models import StripeEvent
from apps.orders.services import handle_stripe_event


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """Stripe delivers each event at-least-once, sometimes more than once.
    The uniqueness of stripe_event_id at the DB level (not an app-level
    exists() check, which would itself race) is what guarantees a payment
    is never processed twice.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        try:
            event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
        except (ValueError, stripe.error.SignatureVerificationError):
            return HttpResponse(status=400)

        # construct_event returns typed StripeObjects (Charge, PaymentIntent,
        # ...), not plain dicts - .get() isn't valid on them, and a JSONField
        # can't serialize them directly either. to_dict() recursively
        # converts the whole event to plain JSON-serializable dicts, which
        # both the metadata lookup below and StripeEvent.payload need.
        event_dict = event.to_dict()

        try:
            with transaction.atomic():
                stripe_event = StripeEvent.objects.create(
                    stripe_event_id=event_dict["id"],
                    event_type=event_dict["type"],
                    order_id=event_dict["data"]["object"].get("metadata", {}).get("order_id"),
                    payload=event_dict,
                )
        except IntegrityError:
            # Duplicate delivery of an event we've already claimed. Ack it
            # so Stripe stops retrying, but never reprocess it here.
            return HttpResponse(status=200)

        handle_stripe_event(stripe_event)
        return HttpResponse(status=200)
