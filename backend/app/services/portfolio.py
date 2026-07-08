"""J15: portfolio roll-up over non-dead pipeline deals.

Pure aggregation: `build_portfolio` takes a list of {id, name, status, inputs}
and computes each deal's engine outputs (pure + LRU-cached). Deals that
can't produce returns (missing required inputs) are the "excluded" set —
listed with a reason and kept out of every equity-weighted blend so a
half-entered deal never silently drags the portfolio IRR. Blends are
equity-weighted on each deal's committed equity; nothing here re-derives a
formula the engine already owns.
"""

from app.services import compute_cache
from app.services.proforma import engine

DEAD_STATUS = "dead"


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _committed_equity(result: dict) -> float:
    """Common equity at close = -levered[0]; falls back to the Equity source
    row. Always a positive dollar figure (0 if all-cash-out, never negative)."""
    statement = result.get("statement") or {}
    levered = statement.get("levered") or []
    if levered:
        return max(0.0, -levered[0])
    for name, amount in (result.get("sourcesAndUses") or {}).get("sources", []):
        if name == "Equity":
            return max(0.0, _num(amount))
    return 0.0


def _total_cost(result: dict, inputs: dict) -> float:
    uses = (result.get("sourcesAndUses") or {}).get("uses", [])
    if uses:
        return sum(_num(a) for _, a in uses)
    return _num(inputs.get("purchasePrice")) or _num(inputs.get("totalCostBasis"))


def _units(inputs: dict) -> float:
    mix = inputs.get("unitMix")
    if isinstance(mix, list):
        return sum(_num(r.get("unitCount")) for r in mix if isinstance(r, dict))
    return _num(inputs.get("keys"))  # hotels


def _square_feet(inputs: dict) -> float:
    sf = _num(inputs.get("rentableSf"))
    leases = inputs.get("commercialLeases")
    if isinstance(leases, list):
        sf += sum(_num(r.get("sf")) for r in leases if isinstance(r, dict))
    mix = inputs.get("unitMix")
    if isinstance(mix, list):
        sf += sum(_num(r.get("unitCount")) * _num(r.get("avgSf")) for r in mix if isinstance(r, dict))
    return sf


def build_portfolio(deals: list[dict]) -> dict:
    """deals: [{id, name, status, inputs}]. Dead deals are dropped entirely
    (they aren't part of the live book)."""
    active = [d for d in deals if (d.get("status") or "screening") != DEAD_STATUS]

    by_status: dict[str, dict] = {}
    market_equity: dict[str, float] = {}
    class_equity: dict[str, float] = {}
    computed: list[dict] = []
    excluded: list[dict] = []

    for deal in active:
        inputs = deal.get("inputs") or {}
        try:
            result = compute_cache.cached_compute(inputs)
        except engine.InsufficientInputsError as exc:
            excluded.append({
                "id": deal.get("id"), "name": deal.get("name"),
                "reason": f"missing inputs: {', '.join(exc.missing)}",
            })
            continue

        outputs = result.get("outputs", {})
        equity = _committed_equity(result)
        cost = _total_cost(result, inputs)
        status = deal.get("status") or "screening"
        market = str(inputs.get("market") or "—")
        asset_class = str(inputs.get("propertyType") or "—")

        bucket = by_status.setdefault(
            status, {"count": 0, "equity": 0.0, "totalCost": 0.0, "units": 0.0, "sf": 0.0}
        )
        bucket["count"] += 1
        bucket["equity"] += equity
        bucket["totalCost"] += cost
        bucket["units"] += _units(inputs)
        bucket["sf"] += _square_feet(inputs)

        market_equity[market] = market_equity.get(market, 0.0) + equity
        class_equity[asset_class] = class_equity.get(asset_class, 0.0) + equity

        computed.append({
            "id": deal.get("id"), "name": deal.get("name"), "status": status,
            "market": market, "assetClass": asset_class, "equity": equity,
            "leveredIrr": outputs.get("leveredIrr"),
            "equityMultiple": outputs.get("equityMultiple"),
        })

    # Equity-weighted blends over deals that HAVE the metric (a computed deal
    # with no IRR — e.g. all-equity edge — still counts its equity elsewhere,
    # but can't weight a blend it has no value for).
    def _weighted(metric: str) -> float | None:
        pairs = [
            (d["equity"], d[metric]) for d in computed
            if isinstance(d.get(metric), (int, float)) and d["equity"] > 0
        ]
        total_equity = sum(w for w, _ in pairs)
        if total_equity <= 0:
            return None
        return sum(w * v for w, v in pairs) / total_equity

    total_equity = sum(b["equity"] for b in by_status.values())
    concentration = sorted(
        (
            {"market": m, "equity": e,
             "sharePct": (e / total_equity) if total_equity > 0 else 0.0}
            for m, e in market_equity.items()
        ),
        key=lambda r: r["equity"], reverse=True,
    )

    return {
        "dealCount": len(computed),
        "excludedCount": len(excluded),
        "totals": {
            "equity": total_equity,
            "totalCost": sum(b["totalCost"] for b in by_status.values()),
            "units": sum(b["units"] for b in by_status.values()),
            "sf": sum(b["sf"] for b in by_status.values()),
        },
        "byStatus": [
            {"status": s, **vals} for s, vals in sorted(by_status.items())
        ],
        "exposureByMarket": [
            {"market": m, "equity": e} for m, e in
            sorted(market_equity.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "exposureByAssetClass": [
            {"assetClass": c, "equity": e} for c, e in
            sorted(class_equity.items(), key=lambda kv: kv[1], reverse=True)
        ],
        "blendedLeveredIrr": _weighted("leveredIrr"),
        "blendedEquityMultiple": _weighted("equityMultiple"),
        "concentration": concentration,
        "deals": computed,
        "excluded": excluded,
    }
