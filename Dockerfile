# Multi-stage secure production Dockerfile for ClipCraft
FROM python:3.11-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Final Runtime Image
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CLIPCRAFT_OUTPUT_DIR=/app/output \
    PORT=8000

WORKDIR /app

# Install runtime FFmpeg with libass & curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libass-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged user for security
RUN groupadd -g 1001 clipcraft && \
    useradd -u 1001 -g clipcraft -s /bin/bash -m clipcraft

COPY --from=builder /install /usr/local

COPY . /app

RUN mkdir -p /app/output/downloads /app/output/shorts && \
    chown -R clipcraft:clipcraft /app

USER clipcraft

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "web.server:app", "--host", "0.0.0.0", "--port", "8000"]

