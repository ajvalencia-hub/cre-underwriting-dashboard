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

    return {
        "exportKind": EXPORT_KIND,
        "schemaVersion": EXPORT_SCHEMA_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "deal": {"name": deal.name, "inputs": deal.inputs},
        "activeTemplate": template_ref,
        "activeMappingProfile": mapping_ref,
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

    db.commit()
    db.refresh(deal)
    out = _to_out(deal)
    # Ride the warnings/counts on the response without a new schema: the
    # client shows them once and they aren't deal state.
    return {**out.model_dump(), "importWarnings": warnings, "importedScenarios": scenario_count}


@router.delete("/{deal_id}")
def delete_deal(deal_id: str, db: Session = Depends(get_db)):
    deal = db.get(Deal, deal_id)
    if deal is None:
        raise HTTPException(404, "Deal not found")
    # Scenarios are meaningless without their deal — cascade, matching how
    # template deletion already removes dependent scenarios.
    db.execute(Scenario.__table__.delete().where(Scenario.deal_id == deal_id))
    db.execute(DealSnapshot.__table__.delete().where(DealSnapshot.deal_id == deal_id))
    db.delete(deal)
    db.commit()
    return {"deleted": True}
