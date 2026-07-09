import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import Base, SessionLocal, engine, run_migrations
from app.routers import (
    agent,
    client_errors,
    comps,
    compute,
    deals,
    demographics,
    documents,
    extraction,
    generate,
    mappings,
    market_context,
    market_rates,
    presets,
    property_tax,
    scenarios,
    schema,
    sensitivity,
    settings,
    templates,
)
from app.services.presets import seed_presets
from app.services.storage_maintenance import sweep_generated_files

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
request_logger = logging.getLogger("app.request")

Base.metadata.create_all(bind=engine)
run_migrations()
sweep_generated_files()
with SessionLocal() as _db:
    seed_presets(_db)

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
        "Content-Disposition",
    ],
)

app.include_router(schema.router)
app.include_router(agent.router)
app.include_router(deals.router)
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
app.include_router(client_errors.router)
app.include_router(settings.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
