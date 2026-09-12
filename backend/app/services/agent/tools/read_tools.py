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
from app.services import compute_cache, goal_seek, mapping_service, sensitivity_service, tornado_service
from app.services.proforma import engine


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
    targetInput: str,
    outputMetric: str,
    targetValue: float,
    values: dict | None = None,
    bounds: list[float] | tuple[float, float] | None = None,
) -> dict:
    """Wraps the J7 goal-seek (app.services.goal_seek) — bracket-scan +
    bisection, no monotonicity assumption, metric-typed tolerance. The
    runner fills `values` with the thread's deal inputs when the model
    omits it (same deal-scoping as get_deal). A found solution and a typed
    no-solution ({"solvedValue": None, "reason": ...}) are both normal
    results; only a malformed request is an {"error": ...}."""
    if values is None:
        return {"error": "No input values available — pass `values` or run this tool inside a deal thread."}
    resolved_bounds: tuple[float, float] | None = None
    if bounds is not None:
        if len(bounds) != 2:
            return {"error": "bounds must be a [low, high] pair."}
        resolved_bounds = (float(bounds[0]), float(bounds[1]))
    try:
        return goal_seek.run_goal_seek(values, targetInput, outputMetric, float(targetValue), resolved_bounds)
    except engine.InsufficientInputsError as exc:
        return {"error": str(exc), "missing": exc.missing}
    except (goal_seek.GoalSeekError, TypeError, ValueError) as exc:
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


def _sale_comp_out(c: SaleComp) -> dict:
    return {
        "id": c.id, "name": c.name, "market": c.market, "price": c.price,
        "units": c.units, "sf": c.sf, "capRatePct": c.cap_rate_pct,
    }


def _rent_comp_out(c: RentComp) -> dict:
    return {
        "id": c.id, "name": c.name, "market": c.market, "unitType": c.unit_type,
        "avgRent": c.avg_rent, "occupancyPct": c.occupancy_pct,
    }


def _comp_in_market(comp_market: str | None, market: str) -> bool:
    if not market.strip():
        return True
    return comps_service.market_matches(comp_market, market)


def list_comps(db: Session, kind: str, market: str = "") -> dict:
    if kind == "sale":
        sale_rows = db.execute(select(SaleComp).order_by(SaleComp.created_at.desc())).scalars()
        comps = [_sale_comp_out(c) for c in sale_rows if _comp_in_market(c.market, market)]
    elif kind == "rent":
        rent_rows = db.execute(select(RentComp).order_by(RentComp.created_at.desc())).scalars()
        comps = [_rent_comp_out(c) for c in rent_rows if _comp_in_market(c.market, market)]
    else:
        return {"error": f"Unknown comp kind '{kind}' — use 'sale' or 'rent'."}
    return {"count": len(comps), "comps": comps}


def get_schema(db: Session) -> dict:
    fields = mapping_service.load_flat_fields(include_outputs=True)
    return {
        "fields": [
            {"id": f["id"], "label": f.get("label"), "type": f.get("type")} for f in fields
        ]
    }
