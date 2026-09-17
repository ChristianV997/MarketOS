FROM python:3.14-slim

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ChristianV997/MarketOS" \
      org.opencontainers.image.revision="${VCS_REF}"

WORKDIR /app

# system deps for lxml, psycopg2-binary, and healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged non-root service account
RUN groupadd -g 10001 marketos && \
    useradd -u 10001 -g marketos -d /app -s /bin/sh marketos

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chown -R marketos:marketos /app

USER marketos

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
