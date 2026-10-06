# ============================================================================
# BEGINNER MAP OF THIS FILE
#
# This is the ONE place in the whole project that Stripe's own servers talk
# to directly - nothing in frontend/ is involved anywhere in this file.
# Flow: Stripe POSTs here -> we verify it's really Stripe (not a forged
# request) -> we "claim" the event (an insert the database itself refuses to
# duplicate) -> we hand it to services.py's handle_stripe_event() to apply
# the actual effect (mark the order paid). See
# reservly-end-to-end-flows.md section 5 for the full story, including WHY
# the browser redirect after payment is NOT what confirms anything - this
# webhook is.
# ============================================================================

import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.views import APIView

from apps.orders.models import StripeEvent
from apps.orders.services import handle_stripe_event


# @csrf_exempt is necessary here (and ONLY here, not on our other views) for
# a specific reason: CSRF protection exists to stop OTHER WEBSITES from
# tricking a logged-in user's browser into submitting a request to us. But
# this request isn't coming from any browser at all - it's Stripe's own
# server making a direct, server-to-server POST. There's no browser/cookie
# session to protect here, and Stripe has no way to attach a CSRF token
# anyway, so the normal protection doesn't apply and has to be turned off
# for this one view specifically.
@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(APIView):
    """Stripe delivers each event at-least-once, sometimes more than once.
    The uniqueness of stripe_event_id at the DB level (not an app-level
    exists() check, which would itself race) is what guarantees a payment
    is never processed twice.
    """

    # Empty lists, deliberately: this endpoint has no logged-in user at all
    # (Stripe isn't "logged in" to our app), so the normal
    # JWTAuthentication/IsAuthenticated checks every other view in this
    # project uses don't apply here. Trust instead comes entirely from the
    # signature check below - that's what proves this request is genuinely
    # from Stripe.
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.body
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE", "")

        # Anyone on the internet could POST fake JSON to this URL pretending
        # to be Stripe. construct_event() checks a cryptographic signature
        # (sig_header) that only Stripe could have produced, proving this
        # really came from them and wasn't tampered with in transit. If that
        # check fails, reject immediately - nothing below this line should
        # ever run for a request that didn't pass it.
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

        # THE ACTUAL DUPLICATE-PROTECTION STEP. We try to save a row
        # recording "we've seen event ID X." The database has a rule (a
        # unique constraint on stripe_event_id, defined on the StripeEvent
        # model) that physically refuses to allow two rows with the same ID.
        # If Stripe sends this exact event twice - which it's explicitly
        # allowed to do - the SECOND save fails here with IntegrityError,
        # caught below, and we stop before ever processing it again.
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

        # Only reached if the claim above succeeded (genuinely new event).
        # This is the "do the actual work" step - see services.py's
        # handle_stripe_event() for what it does, and tasks.py's
        # sweep_unprocessed_stripe_events() for what cleans up if the
        # server crashes between the claim above and this line running.
        handle_stripe_event(stripe_event)
        return HttpResponse(status=200)
