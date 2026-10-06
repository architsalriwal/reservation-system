# This file sets up Celery - the background task system this project uses
# for everything that shouldn't happen inside a normal web request (sending
# an email, running the TTL expiry sweep, etc - see apps/orders/tasks.py for
# all the actual task functions). Two separate processes read this file:
# "celery worker" (which RUNS tasks that get queued with .delay()) and
# "celery beat" (which fires tasks automatically on a repeating schedule -
# that's what `beat_schedule` below configures).
#
# BEGINNER NOTE: this file itself defines NO actual task logic - it's purely
# configuration and scheduling. The real work for every task named below
# lives in apps/orders/tasks.py.

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
# Reuse the same settings.py the rest of Django reads, just looking for
# keys prefixed CELERY_ (e.g. CELERY_BROKER_URL) instead of requiring a
# totally separate config file.
app.config_from_object("django.conf:settings", namespace="CELERY")
# Automatically finds and registers every @shared_task-decorated function
# in every installed app (apps/orders/tasks.py included) - without this,
# Celery wouldn't know these task functions exist at all.
app.autodiscover_tasks()

# The actual "run this automatically, on a timer" schedule. Each entry
# names a task (by its full importable path, as a string) and how often to
# fire it. This is what the celery_beat process reads to decide when to
# queue each task - see docker-compose.prod.yml, where celery_beat runs as
# its own separate container from celery_worker.
app.conf.beat_schedule = {
    "expire-reservations": {
        "task": "apps.orders.tasks.expire_reservations",
        "schedule": 60.0,  # plain number = "every 60 seconds"
    },
    "sweep-unprocessed-stripe-events": {
        "task": "apps.orders.tasks.sweep_unprocessed_stripe_events",
        # crontab(minute="*/2") = "every 2 minutes," using the same scheduling
        # syntax as the Unix `cron` tool - a more flexible alternative to a
        # plain number of seconds, useful for schedules like "every day at
        # 3am" that a plain interval can't express.
        "schedule": crontab(minute="*/2"),
    },
}
