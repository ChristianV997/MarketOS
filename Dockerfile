FROM python:3.12-slim

# Hardening notes (sources adapted, not vendored):
# - Docker docs: USER + HEALTHCHECK + non-root runtime
#   https://docs.docker.com/reference/dockerfile/
# - FastAPI deployment: production image CMD does not enable reload
#   https://fastapi.tiangolo.com/deployment/docker/
# Compatible with existing uvicorn backend.api:app on port 3000.

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ChristianV997/MarketOS" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# system deps for lxml, psycopg2-binary; curl is the HEALTHCHECK client
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 marketos \
    && useradd --system --uid 10001 --gid marketos --home-dir /app --shell /usr/sbin/nologin marketos

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/artifacts \
    && chown -R marketos:marketos /app

USER marketos

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/health || exit 1

STOPSIGNAL SIGINT

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "3000"]
