# Production image for the NoloRoute API (Cloud Run). The same image also runs one-off jobs
# (migrations, POI ingestion) by overriding the command.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is rebuilt only when requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Don't run as root inside the container. /app stays read-only for this user, so the ingest
# script caches its raw API results under /tmp instead.
RUN useradd --create-home --uid 1000 app
USER app
ENV PLACES_CACHE_DIR=/tmp/places-cache

# Cloud Run sends traffic to $PORT (8080 by default).
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
