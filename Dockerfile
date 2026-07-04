# Backend image. Multi-stage so the runtime image doesn't carry pip
# or build tools. NLTK punkt is downloaded at build time so the
# first request doesn't pay a 30s download.
#
# Build:    docker build -t orkaive-backend .
# Run:      docker run -p 8000:8000 --env-file .env orkaive-backend

FROM python:3.12-slim AS builder

WORKDIR /app

# System deps for bcrypt / cryptography wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

WORKDIR /app

# Copy the installed deps from the builder.
COPY --from=builder /install /usr/local

# NLTK data: punkt + punkt_tab are needed by LangChain text splitters.
# Bake them in so the first request doesn't trigger a 30s download.
RUN python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# App code is mounted as a volume in dev; COPY in production images.
COPY app/ ./app/
COPY pytest.ini ./

# Non-root runtime.
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck pings /health every 30s.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://127.0.0.1:8000/health').raise_for_status()" || exit 1

# Single-worker by default; scale with --workers or via compose replicas.
# `--proxy-headers` is required for correct client IPs behind a reverse proxy.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
