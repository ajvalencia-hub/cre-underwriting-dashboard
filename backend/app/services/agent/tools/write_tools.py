"""K3: WRITE tools — the agent's only path to proposing a deal change.

These functions take NO `db: Session` (and no ORM object of any kind) — by
design, not convention. They cannot reach the database, so no matter what
arguments the model passes, they structurally cannot mutate a Deal. Each
returns a Proposal, a plain dataclass; the runner (K4) is the only place a
Proposal ever gets persisted, and even then only as its own row — applying
it to Deal.inputs still requires a separate human-approved PUT
/api/deals/{id}, the exact same endpoint every other edit path already uses.

This is re-verified by a structural test (test_agent_tools.py) that inspects
every write tool's signature and fails the build if one ever gains a `db`
parameter — see K3 in the plan."""

from dataclasses import dataclass, field
from typing import Literal

from app.services import mapping_service
from app.services.proforma import engine


@dataclass
class Proposal:
    kind: Literal["input_changes", "scenario"]
    changes: dict
    rationale: str
    scenarioName: str | None = None
    preview: dict | None = None
    warnings: list[str] = field(default_factory=list)


def _clean_changes(changes: dict) -> tuple[dict, list[str]]:
    fields_by_id = {f["id"]: f for f in mapping_service.load_flat_fields()}
    clean: dict = {}
    warnings: list[str] = []
    for field_id, value in changes.items():
        spec = fields_by_id.get(field_id)
        if spec is None:
            warnings.append(f"'{field_id}' is not a recognized input field — dropped from the proposal.")
            continue
        field_type = spec.get("type")
        if field_type in ("number", "percent") and isinstance(value, bool):
            warnings.append(f"'{field_id}' expects a number, got {value!r} — dropped from the proposal.")
            continue
        if field_type in ("number", "percent") and not isinstance(value, (int, float)):
            warnings.append(f"'{field_id}' expects a number, got {value!r} — dropped from the proposal.")
            continue
        if field_type in ("select", "multiselect"):
            options = spec.get("options", [])
            if options and value not in options:
                warnings.append(f"'{field_id}' value {value!r} isn't one of the allowed options — dropped.")
                continue
        clean[field_id] = value
    return clean, warnings


def _preview(current_values: dict, changes: dict) -> tuple[dict | None, list[str]]:
    trial = {**current_values, **changes}
    try:
        result = engine.compute(trial)
    except engine.InsufficientInputsError as exc:
        return None, [f"Preview unavailable — missing inputs: {', '.join(exc.missing)}."]
    except Exception as exc:  # noqa: BLE001 — preview is best-effort, never blocks the proposal
        return None, [f"Preview failed: {exc}"]
    return {"outputs": result["outputs"], "warnings": result["warnings"]}, []


def propose_input_changes(currentValues: dict, changes: dict, rationale: str) -> Proposal:
    clean, warnings = _clean_changes(changes)
    preview, preview_warnings = _preview(currentValues, clean)
    return Proposal(
        kind="input_changes", changes=clean, rationale=rationale,
        preview=preview, warnings=[*warnings, *preview_warnings],
    )


def propose_scenario(name: str, currentValues: dict, changes: dict, rationale: str) -> Proposal:
    clean, warnings = _clean_changes(changes)
    preview, preview_warnings = _preview(currentValues, clean)
    return Proposal(
        kind="scenario", changes=clean, rationale=rationale, scenarioName=name,
        preview=preview, warnings=[*warnings, *preview_warnings],
    )
