"""Investment-committee sign-off (roadmap #28), local to this app: names are
typed, not logged in. The state is derived from the deal's IcEvent rows:

    draft ──submit──▶ submitted ──approve × N──▶ approved
                        │  ├──reject──▶ rejected
                        │  └──return──▶ draft
    submitted / approved / rejected ──reopen (reason)──▶ draft

While submitted, approved or rejected, the deal's underwriting inputs are
locked (the server refuses changes) so what the committee signed off on is
what the deal says. The Quick Screen napkins, critical dates and field
provenance aren't underwriting inputs and stay editable.
"""

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deal, IcEvent
from app.services import compute_cache
from app.services.proforma import engine

KINDS = ("submit", "approve", "reject", "return", "reopen", "comment")
LOCKED_STATES = ("submitted", "approved", "rejected")
# Keys of Deal.inputs that are not underwriting inputs.
UNLOCKED_KEYS = frozenset({"quickScreen", "acquisitionQuickScreen", "criticalDates", "_provenance"})
# Needs a reason: saying no, sending back, or unlocking a decided deal.
REASON_REQUIRED = frozenset({"reject", "return", "reopen", "comment"})
MAX_REQUIRED_APPROVALS = 9

_ALLOWED: dict[str, tuple[str, ...]] = {
    "draft": ("submit", "comment"),
    "submitted": ("approve", "reject", "return", "reopen", "comment"),
    "approved": ("reopen", "comment"),
    "rejected": ("reopen", "comment"),
}


class IcError(ValueError):
    """A step that's missing what it needs, or (conflict=True) isn't allowed
    in the deal's current state."""

    def __init__(self, message: str, conflict: bool = False):
        super().__init__(message)
        self.conflict = conflict


def events_for(db: Session, deal_id: str) -> list[IcEvent]:
    return list(
        db.execute(
            select(IcEvent).where(IcEvent.deal_id == deal_id).order_by(IcEvent.seq)
        ).scalars().all()
    )


def _norm(name: str) -> str:
    return " ".join(name.split()).casefold()


def derive(events: list[IcEvent]) -> dict:
    """The IC state from the event log: the state, the open submission (if
    any) and who has approved it."""
    state = "draft"
    submission: IcEvent | None = None
    approvers: list[str] = []
    for event in events:
        if event.kind == "submit":
            state, submission, approvers = "submitted", event, []
        elif event.kind == "approve" and state == "submitted" and submission is not None:
            if _norm(event.actor) not in {_norm(a) for a in approvers}:
                approvers.append(event.actor)
            if len(approvers) >= (submission.required_approvals or 1):
                state = "approved"
        elif event.kind == "reject" and state == "submitted":
            state = "rejected"
        elif event.kind in ("return", "reopen"):
            state, submission, approvers = "draft", None, []
    return {"state": state, "submission": submission, "approvers": approvers}


def underwriting_inputs(inputs: dict | None) -> dict:
    return {k: v for k, v in (inputs or {}).items() if k not in UNLOCKED_KEYS}


def is_locked(db: Session, deal_id: str) -> bool:
    return derive(events_for(db, deal_id))["state"] in LOCKED_STATES


def check_input_change(db: Session, deal: Deal, new_inputs: dict) -> None:
    """Raise IcError when `new_inputs` would change a locked deal's
    underwriting inputs."""
    if underwriting_inputs(new_inputs) == underwriting_inputs(deal.inputs):
        return
    state = derive(events_for(db, deal.id))["state"]
    if state in LOCKED_STATES:
        raise IcError(
            f"This deal is {state} by the investment committee, so its inputs are locked. "
            "Reopen it with a reason on the IC Approval tab to change them.",
            conflict=True,
        )


def record(
    db: Session,
    deal: Deal,
    kind: str,
    actor: str,
    comment: str = "",
    required_approvals: int | None = None,
) -> IcEvent:
    """Validate and append one step. A submit computes the deal first and
    stores that result; a deal that can't compute can't go to committee."""
    if kind not in KINDS:
        raise IcError(f"Unknown IC step '{kind}'.")
    actor = " ".join((actor or "").split())
    if not actor:
        raise IcError("Enter your name — every IC step records who took it.")
    comment = (comment or "").strip()
    if kind in REASON_REQUIRED and not comment:
        raise IcError(f"A {kind} needs a reason or comment.")
    events = events_for(db, deal.id)
    current = derive(events)
    if kind not in _ALLOWED[current["state"]]:
        raise IcError(f"Can't {kind} a deal that is {current['state']}.", conflict=True)

    event = IcEvent(deal_id=deal.id, seq=len(events) + 1, kind=kind, actor=actor, comment=comment)
    if kind == "submit":
        needed = required_approvals if required_approvals is not None else 1
        if not 1 <= needed <= MAX_REQUIRED_APPROVALS:
            raise IcError(f"Approvals needed must be between 1 and {MAX_REQUIRED_APPROVALS}.")
        snapshot = underwriting_inputs(deal.inputs)
        try:
            result = compute_cache.cached_compute(snapshot)
        except engine.InsufficientInputsError as exc:
            raise IcError(
                "The deal can't compute yet, so there's nothing to put in front of the committee. "
                f"Missing: {', '.join(exc.missing)}."
            ) from None
        event.required_approvals = needed
        event.inputs = snapshot
        event.outputs = result.get("outputs") or {}
    elif kind == "approve" and _norm(actor) in {_norm(a) for a in current["approvers"]}:
        raise IcError(f"{actor} has already approved this submission.", conflict=True)
    db.add(event)
    db.flush()
    return event


def event_out(event: IcEvent) -> dict:
    created = event.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return {
        "id": event.id,
        "kind": event.kind,
        "actor": event.actor,
        "comment": event.comment,
        "requiredApprovals": event.required_approvals,
        "hasSnapshot": event.inputs is not None,
        "createdAt": created.isoformat(),
    }


def summary(db: Session, deal_id: str) -> dict:
    events = events_for(db, deal_id)
    derived = derive(events)
    submission: IcEvent | None = derived["submission"]
    # The latest version the committee saw, even after a return or reopen,
    # so the tab can show what changed since.
    last_submitted = next((e for e in reversed(events) if e.kind == "submit"), None)
    return {
        "state": derived["state"],
        "locked": derived["state"] in LOCKED_STATES,
        "requiredApprovals": submission.required_approvals if submission else None,
        "approvers": derived["approvers"],
        "lastSubmission": (
            {
                "eventId": last_submitted.id,
                "submittedBy": last_submitted.actor,
                "submittedAt": event_out(last_submitted)["createdAt"],
                "inputs": last_submitted.inputs or {},
                "outputs": last_submitted.outputs or {},
                "current": submission is not None and submission.id == last_submitted.id,
            }
            if last_submitted is not None
            else None
        ),
        "events": [event_out(e) for e in events],
    }


def states_by_deal(db: Session) -> dict[str, str]:
    """Every ACTIVE deal's IC state that isn't draft, for the pipeline.
    Archived deals are hidden from the pipeline, so they drop out here too
    (their events are kept; unarchiving brings the state back)."""
    by_deal: dict[str, list[IcEvent]] = {}
    active = select(Deal.id).where(Deal.archived_at.is_(None))
    for event in db.execute(
        select(IcEvent).where(IcEvent.deal_id.in_(active)).order_by(IcEvent.deal_id, IcEvent.seq)
    ).scalars():
        by_deal.setdefault(event.deal_id, []).append(event)
    out = {}
    for deal_id, events in by_deal.items():
        state = derive(events)["state"]
        if state != "draft":
            out[deal_id] = state
    return out
