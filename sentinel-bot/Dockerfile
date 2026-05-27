FROM python:3.12-slim

WORKDIR /app/sentinel-bot

# Install system dependencies for Playwright/chromium + PostgreSQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY sentinel-bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY sentinel-bot/. .

# Create data directory for SQLite
RUN mkdir -p /app/data

CMD ["python", "main.py"]
