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

COPY backend/ ./backend/
COPY --from=frontend /app/frontend/dist /app/frontend_dist

WORKDIR /app/backend
VOLUME ["/data"]
EXPOSE 8000

# The data volume holds the SQLite DB, uploads, and rotating backups.
# 0.0.0.0 is inside the container (needed for port publishing);
# docker-compose.yml publishes it on 127.0.0.1 only.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
