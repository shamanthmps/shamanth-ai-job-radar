# Dockerfile for JobRadar
FROM python:3.11-slim

WORKDIR /app

# Install system deps for Playwright, ReportLab, psycopg
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium --with-deps

COPY . .

# Ensure resume/ and db/ dirs exist at runtime (mounted as volumes in compose)
RUN mkdir -p resume/generated db

CMD ["python", "scripts/run_pipeline.py", "--mode", "all"]
