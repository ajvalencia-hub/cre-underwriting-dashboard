"""K3: READ/COMPUTE tools — execute immediately, wrap existing services only
(no new math). Every function takes (db: Session, **kwargs) for a uniform
call signature in the runner (K4); write_tools.py is the deliberate
exception — see the docstring there for why.

Failures are returned as {"error": ...} dicts, not raised, so a bad tool
call becomes something the model can see and react to within the same turn
instead of crashing the whole request."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deal, RentComp, SaleComp, Scenario
from app.services import comps as comps_service
from app.services import compute_cache, compute_solver, mapping_service, sensitivity_service, tornado_service
from app.services.proforma import engine

_COMP_KIND_MODELS = {"sale": SaleComp, "rent": RentComp}


def get_deal(db: Session, dealId: str) -> dict:
    deal = db.get(Deal, dealId)
    if deal is None:
        return {"error": f"Deal '{dealId}' not found."}
    return {
        "id": deal.id,
        "name": deal.name,
        "status": deal.status or "screening",
        "inputs": deal.inputs or {},
    }


def list_scenarios(db: Session, dealId: str) -> dict:
    rows = db.execute(
        select(Scenario).where(Scenario.deal_id == dealId).order_by(Scenario.created_at)
    ).scalars().all()
    return {"scenarios": [{"id": s.id, "scenarioName": s.scenario_name, "kind": s.kind} for s in rows]}


def get_scenario(db: Session, scenarioId: str) -> dict:
    scenario = db.get(Scenario, scenarioId)
    if scenario is None:
        return {"error": f"Scenario '{scenarioId}' not found."}
    return {
        "id": scenario.id,
        "scenarioName": scenario.scenario_name,
        "kind": scenario.kind,
        "inputs": scenario.inputs or {},
        "outputs": scenario.outputs or {},
    }


def compute(db: Session, values: dict) -> dict:
    try:
        result = compute_cache.cached_compute(values)
    except engine.InsufficientInputsError as exc:
        return {"error": str(exc), "missing": exc.missing}
    return {
        "outputs": result["outputs"],
        "warnings": result["warnings"],
        "debt": result["debt"],
        "irrConvention": result["irrConvention"],
        "waterfallStyle": result["waterfallStyle"],
    }


def solve(
    db: Session,
    values: dict,
    targetField: str,
    targetMetric: str,
    targetValue: float,
    lowerBound: float,
    upperBound: float,
    tolerance: float = 1e-4,
    maxIterations: int = 50,
) -> dict:
    try:
        return compute_solver.solve(
            values, targetField, targetMetric, targetValue, lowerBound, upperBound, tolerance, maxIterations
        )
    except engine.InsufficientInputsError as exc:
        return {"error": str(exc), "missing": exc.missing}
    except (compute_solver.SolveOutOfRangeError, compute_solver.SolveNoConvergenceError, ValueError) as exc:
        return {"error": str(exc)}


def run_tornado(db: Session, values: dict, metric: str = "leveredIrr") -> dict:
    try:
        return tornado_service.run_tornado(values, metric)
    except engine.InsufficientInputsError as exc:
        return {"error": str(exc), "missing": exc.missing}
    except ValueError as exc:
        return {"error": str(exc)}


def run_sensitivity(db: Session, baseValues: dict, drivers: list[dict], outputFieldIds: list[str]) -> dict:
    total_points = 1
    for d in drivers:
        total_points *= len(d.get("values", []))
    if total_points > sensitivity_service.MAX_NATIVE_GRID_POINTS:
        return {
            "error": f"Grid too large ({total_points} points) — native mode caps at "
            f"{sensitivity_service.MAX_NATIVE_GRID_POINTS} combinations."
        }
    outcome = sensitivity_service.run_native_sensitivity(baseValues, drivers, outputFieldIds)
    return {"points": outcome["points"]}


def get_market_context(db: Session, market: str, submarket: str = "", propertyType: str = "") -> dict:
    from app.services import market_context as market_context_service

    return market_context_service.get_market_context(market, submarket, propertyType)


def list_comps(db: Session, kind: str, market: str = "") -> dict:
    model = _COMP_KIND_MODELS.get(kind)
    if model is None:
        return {"error": f"Unknown comp kind '{kind}' — use 'sale' or 'rent'."}
    rows = db.execute(select(model).order_by(model.created_at.desc())).scalars()
    if market.strip():
        rows = [c for c in rows if comps_service.market_matches(c.market, market)]
    else:
        rows = list(rows)
    if kind == "sale":
        comps = [
            {
                "id": c.id, "name": c.name, "market": c.market, "price": c.price,
                "units": c.units, "sf": c.sf, "capRatePct": c.cap_rate_pct,
            }
            for c in rows
        ]
    else:
        comps = [
            {
                "id": c.id, "name": c.name, "market": c.market, "unitType": c.unit_type,
                "avgRent": c.avg_rent, "occupancyPct": c.occupancy_pct,
            }
            for c in rows
        ]
    return {"count": len(comps), "comps": comps}


def get_schema(db: Session) -> dict:
    fields = mapping_service.load_flat_fields(include_outputs=True)
    return {
        "fields": [
            {"id": f["id"], "label": f.get("label"), "type": f.get("type")} for f in fields
        ]
    }
