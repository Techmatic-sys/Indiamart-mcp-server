# --------------------------------------------------------------------------
# IndiaMART Lead Manager SaaS — Production Docker Image
# --------------------------------------------------------------------------
FROM python:3.12-slim AS base

# Prevent Python from buffering stdout/stderr (useful for container logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by asyncpg & cryptography
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------------------------------
# Dependencies layer (cached independently of source changes)
# --------------------------------------------------------------------------
COPY requirements-saas.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-saas.txt

# --------------------------------------------------------------------------
# Application source
# --------------------------------------------------------------------------
COPY saas/ ./saas/

# --------------------------------------------------------------------------
# Runtime
# --------------------------------------------------------------------------
EXPOSE 8000

# Run with 4 workers in production; override via $WEB_CONCURRENCY
CMD ["uvicorn", "saas.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
