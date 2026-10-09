# Single-container image: backend + embedded scheduler + server-rendered UI.
# Build context must be the PROJECT ROOT (so both backend/ and frontend/ copy in).
# Pin to the Debian codename for a more reproducible base than the floating
# `slim` tag. For full reproducibility, pin by digest (FROM python@sha256:...).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# Install dependencies first for better layer caching.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Application code and the server-rendered frontend (sibling of backend).
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Non-root user; /app/data is the only writable/persisted path.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

# Internal port is configurable via APP_PORT (Coolify-friendly); default 8080.
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8080

EXPOSE 8080

# Liveness probe without needing curl in the image. Honors APP_PORT.
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD python -c "import os,urllib.request,sys; p=os.getenv('APP_PORT','8080'); sys.exit(0 if urllib.request.urlopen(f'http://localhost:{p}/healthz', timeout=4).status==200 else 1)"

# Single worker: the scheduler is embedded in this process (spec section 20).
# Shell form so ${APP_HOST}/${APP_PORT} are honored at runtime.
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"${APP_HOST:-0.0.0.0}\" --port \"${APP_PORT:-8080}\" --workers 1"]
