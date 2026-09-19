import logging
import os
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import Base, SessionLocal, engine, prepare_migrations, run_migrations
from app.services.presets import seed_presets
from app.services.storage_maintenance import sweep_generated_files
from app.routers import (
    admin,
    client_errors,
    comps,
    compute,
    deals,
    demographics,
    documents,
    extraction,
    file_cabinet,
    generate,
    mappings,
    market_context,
    market_rates,
    portfolio,
    presets,
    property_tax,
    schema,
    scenarios,
    search,
    sensitivity,
    templates,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
request_logger = logging.getLogger("app.request")

prepare_migrations()  # refuse a newer database; back up before migrating
Base.metadata.create_all(bind=engine)
run_migrations()
sweep_generated_files()
with SessionLocal() as _db:
    seed_presets(_db)

# J16: the daily backup scheduler is opt-in (the Docker image sets the flag)
# so local dev and the test suite don't spawn a background backup thread.
if os.environ.get("CRE_ENABLE_BACKUP_SCHEDULER") == "1":
    from app.services import backup_service

    backup_service.start_scheduler()

app = FastAPI(title="CRE Underwriting Dashboard API")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """H13: every request gets an id (client-supplied X-Request-ID honored),
    logged with method/path/status/duration and echoed on the response so a
    UI error report can be matched to its server-side line."""
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        request_logger.exception(
            "rid=%s %s %s UNHANDLED", request_id, request.method, request.url.path
        )
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    request_logger.info(
        "rid=%s %s %s -> %s %.1fms",
        request_id, request.method, request.url.path,
        response.status_code, duration_ms,
    )
    response.headers["X-Request-ID"] = request_id
    # Never let a browser guess a type other than the one we declare (an
    # uploaded file sniffed as HTML would run in the app's origin).
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Generation-Warnings",
        "X-Generation-Written-Count",
        "X-Generation-Outputs",
        "X-Deck-Skipped",
        "Content-Disposition",
    ],
)

app.include_router(schema.router)
app.include_router(deals.router)
app.include_router(file_cabinet.router)
app.include_router(compute.router)
app.include_router(templates.router)
app.include_router(mappings.router)
app.include_router(scenarios.router)
app.include_router(generate.router)
app.include_router(market_context.router)
app.include_router(market_rates.router)
app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(sensitivity.router)
app.include_router(property_tax.router)
app.include_router(comps.router)
app.include_router(demographics.router)
app.include_router(presets.router)
app.include_router(portfolio.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(client_errors.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# J16: in the Docker image the backend serves the built SPA. CRE_FRONTEND_DIST
# points at the Vite `dist/`; mounted LAST so every /api route wins, with
# html=True giving SPA fallback for client-side routes. Absent in dev (Vite
# serves the frontend), so this is a no-op there.
_frontend_dist = os.environ.get("CRE_FRONTEND_DIST")
if _frontend_dist and os.path.isdir(_frontend_dist):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="spa")
