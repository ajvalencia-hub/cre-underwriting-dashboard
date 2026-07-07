"""K8: a compact deal-state summary seeded into the system prompt on every
turn, so the model doesn't need a throwaway get_deal call just to know
which deal it's looking at. This is context, not a claim — the runner
labels it as database-sourced, not tool-verified, and the provenance
checker (K5) still requires a real tool call for any number the model
states back to the user."""

from sqlalchemy.orm import Session

from app.models import Deal

_KEY_FIELDS = ["purchasePrice", "holdPeriodYears", "exitCapRatePct", "grossPotentialRent"]


def build_context_seed(db: Session, deal_id: str) -> str:
    deal = db.get(Deal, deal_id)
    if deal is None:
        return ""
    inputs = deal.inputs or {}
    parts = [f'Deal: "{deal.name}" (status: {deal.status or "screening"})']

    deal_type = inputs.get("dealType")
    property_type = inputs.get("propertyType")
    if deal_type:
        type_str = str(deal_type)
        if property_type:
            type_str += f" / {property_type}"
        parts.append(f"Type: {type_str}")

    market = inputs.get("market")
    if market:
        parts.append(f"Market: {market}")

    known = {f: inputs[f] for f in _KEY_FIELDS if f in inputs}
    if known:
        parts.append(f"Key inputs on file: {known}")

    return " | ".join(parts)
