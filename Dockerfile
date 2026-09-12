# J16: single image — build the SPA, then serve it from the FastAPI backend
# which also carries LibreOffice (Excel parity / recalc), Tesseract (OCR), and
# Poppler (PDF rasterize) so every server-side path works in the container.

# --- Stage 1: build the frontend ---
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend runtime ---
FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CRE_STORAGE_ROOT=/data \
    CRE_FRONTEND_DIST=/app/frontend_dist \
    CRE_ENABLE_BACKUP_SCHEDULER=1

# System deps: LibreOffice (headless recalc for parity + memo PDF), Tesseract
# (scanned-PDF OCR), Poppler (pdf2image rasterize).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-calc libreoffice-writer tesseract-ocr poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Only the application package (+ the seed script) — tests, fixtures and the
# parity corpus stay out of the runtime image.
COPY backend/app/ ./backend/app/
COPY backend/scripts/ ./backend/scripts/
COPY --from=frontend /app/frontend/dist /app/frontend_dist

# Run as an unprivileged user. /data (the volume) and HOME must be writable:
# LibreOffice bootstraps a per-run profile and matplotlib a font cache under
# HOME. Upgrading a volume created by an older (root) image? Run once:
#   docker compose run --rm --user root app chown -R app:app /data
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /data /app
USER app

WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8000

# Container-level liveness: the same /api/health the CI smoke curls. Uses the
# interpreter already in the image (no curl in python:*-slim).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# The data volume holds the SQLite DB, uploads, and rotating backups.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
