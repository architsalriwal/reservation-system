from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"

    def ready(self):
        # stripe-python has no per-call timeout parameter in this version -
        # it's configured once on the HTTP client instead. Set it here so
        # every Stripe call fails fast rather than hanging the checkout
        # request open if Stripe is slow/unreachable.
        import stripe
        from stripe._http_client import RequestsClient

        from apps.orders.views import STRIPE_REQUEST_TIMEOUT_SECONDS

        stripe.default_http_client = RequestsClient(timeout=STRIPE_REQUEST_TIMEOUT_SECONDS)  # noqa: E501
