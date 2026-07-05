from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import Base, SessionLocal, engine, run_migrations
from app.services.presets import seed_presets
from app.services.storage_maintenance import sweep_generated_files
from app.routers import (
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
    schema,
    scenarios,
    sensitivity,
    templates,
)

Base.metadata.create_all(bind=engine)
run_migrations()
sweep_generated_files()
with SessionLocal() as _db:
    seed_presets(_db)

app = FastAPI(title="CRE Underwriting Dashboard API")

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


@app.get("/api/health")
def health():
    return {"status": "ok"}
