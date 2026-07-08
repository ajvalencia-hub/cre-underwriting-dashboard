import json
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse, Response

from app.database import get_db
from app.models import Deal, DealSnapshot, MappingProfile, Scenario, Template
from app.schemas import DealIn, DealOut, DealUpdate
from app.services import deal_history, deck_service, share_html
from app.services.proforma import engine

PPTX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

router = APIRouter(prefix="/api/deals", tags=["deals"])

EXPORT_KIND = "cre-dashboard-deal"
EXPORT_SCHEMA_VERSION = 1


def _to_out(deal: Deal) -> DealOut:
    return DealOut(
        id=deal.id,
        name=deal.name,
        inputs=deal.inputs,
        status=deal.status or "screening",
        activeTemplateId=deal.active_template_id,
        activeMappingProfileId=deal.active_mapping_profile_id,
        createdAt=deal.created_at,
        updatedAt=deal.updated_at,
    )


@router.get("", response_model=list[DealOut])
def list_deals(db: Session = Depends(get_db)):
    deals = db.execute(select(Deal).order_by(Deal.updated_at.desc())).scalars().all()
    return [_to_out(d) for d in deals]


@router.post("", response_model=DealOut)
def create_deal(payload: DealIn, db: Session = Depends(get_db)):
    if not payload.name.strip():
        raise HTTPException(400, "Deal name cannot be empty")
    deal = Deal(name=payload.name.strip(), inputs=payload.inputs)
    db.add(deal)
    db.commit()
    db.refresh(deal)
    return _to_out(deal)


class FromExtractionRequest(BaseModel):
    # J10: the wizard's finalize step. confirmedValues are the REVIEWED
    # values from the extraction gate — nothing here was auto-applied.
    name: str
    extractionResultId: str
    confirmedValues: dict[str, Any]
    acknowledgeFailures: bool = False
    dealId: str | None = None  # finalize an existing wizard draft in place


@router.post("/from-extraction", response_model=DealOut)
def create_deal_from_extraction(payload: FromExtractionRequest, db: Session = Depends(get_db)):
    """J10: create (or finalize a draft) deal from a reviewed extraction.
    Blocking cross-validation failures carry the SAME acknowledgment
    mechanics as the review gate — unacknowledged failures are a 409 here
    too, so the gate can't be bypassed by calling the API directly.
    Provenance rows link every populated field to its source document."""
    from app.models import ExtractionResult

    if not payload.name.strip():
        raise HTTPException(400, "Deal name cannot be empty")
    stored = db.get(ExtractionResult, payload.extractionResultId)
    if stored is None:
        raise HTTPException(404, "Extraction result not found")

    failures = [
        check for check in (stored.cross_validation or [])
        if check.get("status") == "fail"
    ]
    if failures and not payload.acknowledgeFailures:
        raise HTTPException(
            409,
            detail={
                "message": "Blocking cross-validation failures must be "
                "acknowledged before creating a deal.",
                "failures": failures,
            },
        )

    # Provenance: reviewed values that map to an extracted field carry its
    # sourceRef/confidence; proposal-shaped values (unit mix, lease roll)
    # trace to the reviewed proposal.
    provenance: dict[str, dict] = {}
    fields = stored.fields or {}
    for field_id in payload.confirmedValues:
        entry = fields.get(field_id)
        if isinstance(entry, dict):
            provenance[field_id] = {
                "sourceRef": entry.get("sourceRef"),
                "confidence": entry.get("confidence"),
                "source": entry.get("source"),
            }
        else:
            provenance[field_id] = {"source": "reviewed_proposal"}

    inputs: dict[str, Any] = dict(payload.confirmedValues)
    inputs["dealName"] = payload.name.strip()
    inputs["_provenance"] = provenance

    # The existing confirm mechanics — the extraction records what was
    # reviewed and when, exactly as the standalone review gate does.
    stored.confirmed_values = payload.confirmedValues
    stored.confirmed_at = datetime.now(timezone.utc)

    if payload.dealId:
        deal = db.get(Deal, payload.dealId)
        if deal is None:
            raise HTTPException(404, "Draft deal not found")
        merged = {
            key: value
            for key, value in (deal.inputs or {}).items()
            if key != "_omWizard"
        }
        merged.update(inputs)
        deal_history.record_snapshot(db, deal, merged)
        deal.inputs = merged
        deal.name = payload.name.strip()
    else:
        deal = Deal(name=payload.name.strip(), inputs=inputs)
        db.add(deal)
    db.commit()
    db.refresh(deal)
    return _to_out(deal)


@router.get("/{deal_id}", response_model=DealOut)
def get_deal(deal_id: str, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    return _to_out(deal)


@router.put("/{deal_id}", response_model=DealOut)
def update_deal(deal_id: str, payload: DealUpdate, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")

    # Partial-update semantics: only fields present in the request body are
    # applied, so the autosave (inputs only) can't clobber a concurrent
    # template selection (activeTemplateId only) and vice versa.
    provided = payload.model_fields_set
    if "name" in provided:
        if not (payload.name or "").strip():
            raise HTTPException(400, "Deal name cannot be empty")
        deal.name = payload.name.strip()
    if "inputs" in provided and payload.inputs is not None:
        deal_history.record_snapshot(db, deal, payload.inputs)
        deal.inputs = payload.inputs
    if "status" in provided and payload.status is not None:
        deal.status = payload.status
    if "activeTemplateId" in provided:
        deal.active_template_id = payload.activeTemplateId
    if "activeMappingProfileId" in provided:
        deal.active_mapping_profile_id = payload.activeMappingProfileId

    db.commit()
    db.refresh(deal)
    return _to_out(deal)


class BulkStatusRequest(BaseModel):
    dealIds: list[str]
    status: str


@router.post("/bulk-status")
def bulk_status(payload: BulkStatusRequest, db: Session = Depends(get_db)):
    """I10: one stage change across many pipeline rows. Unknown ids are
    reported, not silently dropped; invalid stages are rejected before
    anything is written."""
    from app.schemas import DEAL_STATUSES

    if payload.status not in DEAL_STATUSES:
        raise HTTPException(422, f"Unknown status '{payload.status}'.")
    if not payload.dealIds:
        raise HTTPException(400, "dealIds is empty.")
    updated: list[DealOut] = []
    missing: list[str] = []
    for deal_id in payload.dealIds:
        deal = db.get(Deal, deal_id)
        if deal is None:
            missing.append(deal_id)
            continue
        deal.status = payload.status
        updated.append(deal)
    db.commit()
    for deal in updated:
        db.refresh(deal)
    return {
        "updated": [_to_out(d).model_dump() for d in updated],
        "missing": missing,
    }


class BatchDeckRequest(BaseModel):
    dealIds: list[str]


@router.post("/batch-deck")
def batch_deck(payload: BatchDeckRequest, db: Session = Depends(get_db)):
    """I13: one screening .pptx — a title slide plus one H12-style slide per
    computable deal, in the ORDER GIVEN (the client sends the pipeline's
    current sort). Incomputable deals are skipped and listed, both on the
    title slide and in the X-Deck-Skipped header. Hard cap 20 deals."""
    from app.services.deck_service import BATCH_DECK_CAP, build_batch_deck

    if not payload.dealIds:
        raise HTTPException(400, "dealIds is empty.")
    if len(payload.dealIds) > BATCH_DECK_CAP:
        raise HTTPException(
            422,
            f"Batch deck is capped at {BATCH_DECK_CAP} deals per file "
            f"({len(payload.dealIds)} requested) — narrow the selection.",
        )

    entries: list[dict] = []
    skipped: list[str] = []
    for deal_id in payload.dealIds:
        deal = db.get(Deal, deal_id)
        if deal is None:
            skipped.append(deal_id)
            continue
        try:
            result = engine.compute(deal.inputs or {})
        except Exception:  # noqa: BLE001 — an incomputable deal skips, never kills the deck
            skipped.append(deal.name)
            continue
        entries.append({"name": deal.name, "inputs": deal.inputs or {}, "result": result})

    if not entries:
        raise HTTPException(422, "None of the selected deals are computable.")

    content = build_batch_deck(entries, skipped)
    return Response(
        content=content,
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="screening-deck.pptx"',
            "X-Deck-Skipped": json.dumps(skipped),
        },
    )


@router.get("/{deal_id}/history")
def deal_history_list(deal_id: str, db: Session = Depends(get_db)):
    """Snapshot list, newest first — metadata only (full inputs stay on the
    server until a restore)."""
    if db.get(Deal, deal_id) is None:
        raise HTTPException(404, "Deal not found")
    return [
        {
            "id": s.id,
            "kind": s.kind,
            "changedPaths": s.changed_paths or [],
            "createdAt": s.created_at,
            "updatedAt": s.updated_at,
        }
        for s in deal_history.list_snapshots(db, deal_id)
    ]


@router.get("/{deal_id}/history/{snapshot_id}")
def get_snapshot(deal_id: str, snapshot_id: str, db: Session = Depends(get_db)):
    """I12: one snapshot WITH its full inputs — fetched on demand for the
    diff/compare views (the list endpoint stays metadata-only)."""
    snapshot = db.get(DealSnapshot, snapshot_id)
    if snapshot is None or snapshot.deal_id != deal_id:
        raise HTTPException(404, "Snapshot not found")
    return {
        "id": snapshot.id,
        "kind": snapshot.kind,
        "changedPaths": snapshot.changed_paths or [],
        "inputs": snapshot.inputs,
        "createdAt": snapshot.created_at,
        "updatedAt": snapshot.updated_at,
    }


@router.post("/{deal_id}/history/{snapshot_id}/restore", response_model=DealOut)
def restore_snapshot(deal_id: str, snapshot_id: str, db: Session = Depends(get_db)):
    """Sets the deal's inputs back to the snapshot's state. The restore is
    recorded as its own snapshot, so it can itself be undone."""
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    snapshot = db.get(DealSnapshot, snapshot_id)
    if snapshot is None or snapshot.deal_id != deal_id:
        raise HTTPException(404, "Snapshot not found")
    deal_history.record_snapshot(db, deal, snapshot.inputs, kind="restore")
    deal.inputs = snapshot.inputs
    db.commit()
    db.refresh(deal)
    return _to_out(deal)


@router.get("/{deal_id}/share.html", response_class=HTMLResponse)
def share_deal(deal_id: str, db: Session = Depends(get_db)):
    """Self-contained read-only HTML snapshot (H10): inline CSS, no scripts,
    no external requests — computed fresh from the deal's saved inputs."""
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    inputs = deal.inputs or {}
    try:
        result = engine.compute(inputs)
        error = None
    except engine.InsufficientInputsError as exc:
        result = None
        error = f"This deal can't be computed yet — missing inputs: {', '.join(exc.missing)}."
    except Exception as exc:  # noqa: BLE001 — a share link must never 500 into a stack trace
        result = None
        error = f"Compute failed: {exc}"
    page = share_html.render_share_html(
        deal.name, deal.status or "screening", inputs, result, error
    )
    safe_name = re.sub(r"[^A-Za-z0-9 _.-]", "", deal.name).strip()[:60] or "deal"
    return HTMLResponse(
        content=page,
        headers={"Content-Disposition": f'inline; filename="{safe_name}-share.html"'},
    )


@router.get("/{deal_id}/deck.pptx")
def deal_deck(deal_id: str, db: Session = Depends(get_db)):
    """One-page investment-summary deck (H12) — computed fresh, zero math in
    the renderer (same rule as the memo and HTML share)."""
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    try:
        result = engine.compute(deal.inputs or {})
    except engine.InsufficientInputsError as exc:
        raise HTTPException(
            422, f"Deck needs a computable deal — missing inputs: {', '.join(exc.missing)}."
        ) from exc
    content = deck_service.build_deck(deal.name, deal.inputs or {}, result)
    safe_name = re.sub(r"[^A-Za-z0-9 _.-]", "", deal.name).strip()[:60] or "deal"
    return Response(
        content=content,
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-summary.pptx"'
        },
    )


@router.get("/{deal_id}/ic-deck.pptx")
def deal_ic_deck(deal_id: str, scenario_id: str | None = None, db: Session = Depends(get_db)):
    """J14: the full 8-slide IC deck. Optional scenario_id supplies saved
    sensitivity + Monte Carlo runs (their slides skip without it). Market
    context/demographics are best-effort (external sources; skip when
    offline). Skipped slide keys ride the X-Deck-Skipped response header."""
    from app.models import Scenario as _Scenario
    from app.services import benchmarks as _benchmarks
    from app.services import demographics as _demographics
    from app.services import tornado_service

    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    inputs = deal.inputs or {}
    try:
        result = engine.compute(inputs)
    except engine.InsufficientInputsError as exc:
        raise HTTPException(
            422, f"Deck needs a computable deal — missing inputs: {', '.join(exc.missing)}."
        ) from exc

    sensitivity = monte_carlo = None
    if scenario_id:
        scenario = db.get(_Scenario, scenario_id)
        if scenario is not None:
            sensitivity = scenario.sensitivity
            monte_carlo = scenario.monte_carlo

    tornado = None
    try:
        tornado = tornado_service.run_tornado(inputs, "leveredIrr")
    except (engine.InsufficientInputsError, ValueError):
        tornado = None

    benchmark_data = demographic_data = None
    market = str(inputs.get("market") or "")
    address = str(inputs.get("address") or "")
    if market or address:
        try:
            benchmark_data = _benchmarks.build_benchmarks(
                address, market, str(inputs.get("submarket") or ""),
                str(inputs.get("propertyType") or ""),
                {"rentGrowthPct": _num_or_none(inputs.get("rentGrowthPct"))},
            )
        except Exception:  # noqa: BLE001 - external sources must not fail the deck
            benchmark_data = None
        try:
            demographic_data = _demographics.get_demographic_trends(
                market, str(inputs.get("submarket") or ""), address
            )
        except Exception:  # noqa: BLE001
            demographic_data = None

    content, skipped = deck_service.build_ic_deck(
        deal.name, inputs, result,
        sensitivity=sensitivity, monte_carlo=monte_carlo,
        benchmarks=benchmark_data, demographics=demographic_data, tornado=tornado,
    )
    safe_name = re.sub(r"[^A-Za-z0-9 _.-]", "", deal.name).strip()[:60] or "deal"
    return Response(
        content=content,
        media_type=PPTX_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-ic-deck.pptx"',
            "X-Deck-Skipped": ",".join(skipped),
        },
    )


def _num_or_none(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


@router.get("/{deal_id}/export")
def export_deal(deal_id: str, db: Session = Depends(get_db)):
    """Versioned, self-contained JSON bundle for one deal: inputs (incl. the
    quickScreen key), scenarios with their outputs and saved sensitivity
    runs, and NAMED template/mapping references (the underlying .xlsx is
    deliberately not bundled). Documents and extraction results are global,
    not deal-scoped, so the bundle carries none (see DECISIONS.md)."""
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")

    scenarios = db.execute(
        select(Scenario).where(Scenario.deal_id == deal_id).order_by(Scenario.created_at)
    ).scalars().all()

    template_ref = None
    if deal.active_template_id:
        template = db.get(Template, deal.active_template_id)
        template_ref = {"id": deal.active_template_id, "filename": template.filename if template else None}
    mapping_ref = None
    if deal.active_mapping_profile_id:
        profile = db.get(MappingProfile, deal.active_mapping_profile_id)
        mapping_ref = {
            "id": deal.active_mapping_profile_id,
            "profileName": profile.profile_name if profile else None,
        }

    # J12: notes travel in the bundle; attachments are listed by name/hash
    # but NOT embedded — bundles stay small, diffable JSON, and the hash
    # lets the receiving side verify a manually-transferred file. (Embedding
    # base64 blobs was rejected: a 20MB OM would dwarf the deal data.)
    from app.models import DealNote, Document

    notes = db.execute(
        select(DealNote).where(DealNote.deal_id == deal_id).order_by(DealNote.created_at)
    ).scalars().all()
    attachments = db.execute(
        select(Document).where(Document.deal_id == deal_id).order_by(Document.created_at)
    ).scalars().all()

    return {
        "exportKind": EXPORT_KIND,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "deal": {"name": deal.name, "inputs": deal.inputs},
        "activeTemplate": template_ref,
        "activeMappingProfile": mapping_ref,
        "notes": [
            {"body": n.body, "createdAt": n.created_at.isoformat()} for n in notes
        ],
        "attachments": [
            {"filename": a.filename, "fileHash": a.file_hash, "fileExt": a.file_ext}
            for a in attachments
        ],
        "scenarios": [
            {
                "scenarioName": s.scenario_name,
                "kind": s.kind,
                "templateId": s.template_id,
                "mappingProfileId": s.mapping_profile_id,
                "inputs": s.inputs,
                "outputs": s.outputs,
                "sensitivity": s.sensitivity,
            }
            for s in scenarios
        ],
    }


class DealImportRequest(BaseModel):
    bundle: dict[str, Any]


@router.post("/import")
def import_deal(payload: DealImportRequest, db: Session = Depends(get_db)):
    """Creates a NEW deal from an exported bundle — never merges. Internal
    ids are rewritten; template/mapping references import as named
    placeholders (cleared ids) since the .xlsx isn't bundled."""
    bundle = payload.bundle
    if bundle.get("exportKind") != EXPORT_KIND:
        raise HTTPException(400, "Not a deal export bundle (exportKind mismatch).")
    if bundle.get("schemaVersion") != EXPORT_SCHEMA_VERSION:
        raise HTTPException(
            400,
            f"Unsupported bundle schemaVersion {bundle.get('schemaVersion')!r} — "
            f"this build reads version {EXPORT_SCHEMA_VERSION}.",
        )
    deal_data = bundle.get("deal") or {}
    name = str(deal_data.get("name") or "Imported Deal").strip() or "Imported Deal"
    inputs = deal_data.get("inputs") if isinstance(deal_data.get("inputs"), dict) else {}

    deal = Deal(name=f"{name} (imported)", inputs=inputs)
    db.add(deal)
    db.flush()  # assigns the new deal id for the scenarios below

    warnings: list[str] = []
    if bundle.get("activeTemplate") or bundle.get("activeMappingProfile"):
        template_name = (bundle.get("activeTemplate") or {}).get("filename") or "unknown template"
        warnings.append(
            f"The exporting machine used template '{template_name}' — templates aren't "
            "bundled, so re-upload the .xlsx and re-map under 'Template & Mapping'."
        )

    scenario_count = 0
    for s in bundle.get("scenarios") or []:
        if not isinstance(s, dict) or not s.get("scenarioName"):
            continue
        kind = s.get("kind") if s.get("kind") in ("quickscreen", "full") else "full"
        if s.get("templateId") or s.get("mappingProfileId"):
            warnings.append(
                f"Scenario '{s['scenarioName']}': template/mapping references were "
                "cleared (not bundled) — re-link after re-uploading the template."
            )
        db.add(
            Scenario(
                scenario_name=str(s["scenarioName"]),
                kind=kind,
                deal_id=deal.id,
                template_id=None,
                mapping_profile_id=None,
                inputs=s.get("inputs") if isinstance(s.get("inputs"), dict) else {},
                outputs=s.get("outputs") if isinstance(s.get("outputs"), dict) else {},
                sensitivity=s.get("sensitivity") if isinstance(s.get("sensitivity"), dict) else None,
            )
        )
        scenario_count += 1

    # J12: notes import (they're plain text); attachments are name/hash
    # listings only — surface what the exporter had so the user can move
    # the files by hand.
    from app.models import DealNote

    note_count = 0
    for n in bundle.get("notes") or []:
        if isinstance(n, dict) and str(n.get("body") or "").strip():
            db.add(DealNote(deal_id=deal.id, body=str(n["body"])))
            note_count += 1
    listed_attachments = [
        a for a in (bundle.get("attachments") or [])
        if isinstance(a, dict) and a.get("filename")
    ]
    if listed_attachments:
        names = ", ".join(str(a["filename"]) for a in listed_attachments[:5])
        warnings.append(
            f"The bundle lists {len(listed_attachments)} attachment(s) by "
            f"name/hash ({names}{'…' if len(listed_attachments) > 5 else ''}) — "
            "files are not embedded; transfer and re-upload them to this deal."
        )

    db.commit()
    db.refresh(deal)
    out = _to_out(deal)
    # Ride the warnings/counts on the response without a new schema: the
    # client shows them once and they aren't deal state.
    return {
        **out.model_dump(),
        "importWarnings": warnings,
        "importedScenarios": scenario_count,
        "importedNotes": note_count,
    }


@router.delete("/{deal_id}")
def delete_deal(deal_id: str, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    # Scenarios are meaningless without their deal — cascade, matching how
    # template deletion already removes dependent scenarios. J12: notes and
    # deal-scoped attachments cascade too (files unlink only when no other
    # document row shares the hash — uploads dedupe by content).
    from pathlib import Path as _Path

    from app.models import DealNote, Document

    db.execute(Scenario.__table__.delete().where(Scenario.deal_id == deal_id))
    db.execute(DealSnapshot.__table__.delete().where(DealSnapshot.deal_id == deal_id))
    db.execute(DealNote.__table__.delete().where(DealNote.deal_id == deal_id))
    attachments = db.execute(
        select(Document).where(Document.deal_id == deal_id)
    ).scalars().all()
    for doc in attachments:
        others = db.execute(
            select(Document).where(
                Document.file_hash == doc.file_hash, Document.id != doc.id
            )
        ).scalars().first()
        if others is None:
            _Path(doc.stored_path).unlink(missing_ok=True)
        db.delete(doc)
    db.delete(deal)
    db.commit()
    return {"deleted": True}
