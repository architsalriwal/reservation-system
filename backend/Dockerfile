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

RUN adduser --disabled-password --no-create-home appuser
USER appuser

EXPOSE 8000

# daphne serves the ASGI app for both HTTP and WebSocket traffic on one
# process type - gunicorn+wsgi can't handle the /ws/ routes at all.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
