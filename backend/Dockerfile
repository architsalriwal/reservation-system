FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# staticfiles/ is gitignored (collectstatic generates it at runtime), so
# it doesn't exist in the image after COPY . . - mkdir it explicitly so
# there's something for the chown below to own. Without this, Docker
# creates the staticfiles/ mount point itself the first time the named
# volume attaches, as a fresh root:root directory with no connection to
# the image's ownership - appuser then can't write into it, and
# collectstatic fails with "Permission denied: '/code/staticfiles/admin'"
# the moment it hits a brand-new volume (an old volume that happened to
# get initialized correctly once keeps working, which is why this stayed
# latent until a fresh deployment actually created one from scratch).
#
# appuser needs to own the whole working directory, not just
# /code/staticfiles: celery beat writes its schedule file to the cwd
# (celerybeat-schedule), which fails with Permission denied against a
# root-owned /code just like collectstatic did against a root-owned
# staticfiles/. Chowning /code as a whole (before the staticfiles volume
# overlay attaches) covers both, and anything else that assumes cwd is
# writable, in one place instead of chasing each write site individually.
RUN mkdir -p /code/staticfiles \
    && adduser --disabled-password --no-create-home appuser \
    && chown -R appuser:appuser /code
USER appuser

EXPOSE 8000

# daphne serves the ASGI app for both HTTP and WebSocket traffic on one
# process type - gunicorn+wsgi can't handle the /ws/ routes at all.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
