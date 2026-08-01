FROM python:3.12-slim

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/ChristianV997/MarketOS" \
      org.opencontainers.image.revision="${VCS_REF}"

WORKDIR /app

# system deps for lxml, psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3000

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "3000"]
