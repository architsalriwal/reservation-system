import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "expire-reservations": {
        "task": "apps.orders.tasks.expire_reservations",
        "schedule": 60.0,
    },
    "sweep-unprocessed-stripe-events": {
        "task": "apps.orders.tasks.sweep_unprocessed_stripe_events",
        "schedule": crontab(minute="*/2"),
    },
}
