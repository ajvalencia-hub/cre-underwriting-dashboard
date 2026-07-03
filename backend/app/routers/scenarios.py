from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Deal, Scenario, Template
from app.routers.generate import _content_disposition
from app.schemas import ScenarioIn, ScenarioOut, ScenarioUpdate
from app.services import benchmarks, memo_service
from app.services.proforma import engine

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _to_out(scenario: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=scenario.id,
        scenarioName=scenario.scenario_name,
        kind=scenario.kind,
        dealId=scenario.deal_id,
        templateId=scenario.template_id,
        mappingProfileId=scenario.mapping_profile_id,
        inputs=scenario.inputs,
        outputs=scenario.outputs,
        createdAt=scenario.created_at,
        updatedAt=scenario.updated_at,
    )


@router.get("", response_model=list[ScenarioOut])
def list_scenarios(
    template_id: str | None = None,
    kind: str | None = None,
    deal_id: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(Scenario)
    if template_id:
        stmt = stmt.where(Scenario.template_id == template_id)
    if kind:
        stmt = stmt.where(Scenario.kind == kind)
    if deal_id:
        stmt = stmt.where(Scenario.deal_id == deal_id)
    scenarios = db.execute(stmt.order_by(Scenario.updated_at.desc())).scalars().all()
    return [_to_out(s) for s in scenarios]


@router.post("", response_model=ScenarioOut)
def create_scenario(payload: ScenarioIn, db: Session = Depends(get_db)):
    if payload.kind == "full":
        if not payload.templateId or not payload.mappingProfileId:
            raise HTTPException(400, "Full scenarios require a templateId and mappingProfileId")
        template = db.get(Template, payload.templateId)
        if template is None:
            raise HTTPException(404, "Template not found")

    scenario = Scenario(
        scenario_name=payload.scenarioName,
        kind=payload.kind,
        deal_id=payload.dealId,
        template_id=payload.templateId,
        mapping_profile_id=payload.mappingProfileId,
        inputs=payload.inputs,
        outputs=payload.outputs or {},
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return _to_out(scenario)


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    return _to_out(scenario)


@router.put("/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: str, payload: ScenarioUpdate, db: Session = Depends(get_db)):
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")

    # kind and templateId used to be silently ignored on update (FINDINGS.md
    # M14). kind is immutable — flipping quickscreen<->full changes which
    # fields are required — so a differing value is rejected, not dropped.
    # templateId is applied, under the same validation create enforces.
    if payload.kind is not None and payload.kind != scenario.kind:
        raise HTTPException(
            400, f"Scenario kind cannot be changed (this is a '{scenario.kind}' scenario)"
        )
    if scenario.kind == "full":
        if not payload.templateId or not payload.mappingProfileId:
            raise HTTPException(400, "Full scenarios require a templateId and mappingProfileId")
        if db.get(Template, payload.templateId) is None:
            raise HTTPException(404, "Template not found")

    scenario.scenario_name = payload.scenarioName
    if payload.dealId is not None:
        scenario.deal_id = payload.dealId
    scenario.template_id = payload.templateId
    scenario.mapping_profile_id = payload.mappingProfileId
    scenario.inputs = payload.inputs
    if payload.outputs is not None:
        scenario.outputs = payload.outputs
    db.commit()
    db.refresh(scenario)
    return _to_out(scenario)


class MemoRequest(BaseModel):
    limitationsText: str | None = None


@router.post("/{scenario_id}/memo")
def generate_memo(scenario_id: str, payload: MemoRequest, db: Session = Depends(get_db)):
    """Render the IC memo .docx. Numbers come ONLY from a fresh engine compute
    of the scenario's inputs, falling back to the scenario's stored outputs —
    the memo service itself contains zero financial math."""
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    if scenario.kind != "full":
        raise HTTPException(
            400, "Quick Screen scenarios don't carry the full inputs an IC memo needs."
        )

    inputs = scenario.inputs or {}
    stored = scenario.outputs or {}
    sources_and_uses = None
    try:
        computed = engine.compute(inputs)
        metrics = computed["outputs"]
        debt = computed["debt"]
        sources_and_uses = computed["sourcesAndUses"]
    except engine.InsufficientInputsError as exc:
        metrics = stored.get("metrics") or {}
        debt = stored.get("debt")
        if not metrics:
            raise HTTPException(
                422,
                "Scenario has no stored outputs and its inputs are insufficient "
                f"for a fresh compute (missing: {', '.join(exc.missing)}).",
            ) from exc

    # Market flags are context; a failed/offline lookup never blocks the memo.
    benchmark_flags = None
    address = str(inputs.get("address") or "")
    market = str(inputs.get("market") or "")
    if address or market:
        try:
            result = benchmarks.build_benchmarks(
                address, market, str(inputs.get("submarket") or ""),
                str(inputs.get("propertyType") or ""),
                benchmarks.derive_subject_from_inputs(inputs),
            )
            benchmark_flags = result["flags"] or None
        except Exception:  # noqa: BLE001
            benchmark_flags = None

    deal = db.get(Deal, scenario.deal_id) if scenario.deal_id else None
    deal_name = (
        (deal.name if deal else None)
        or str(inputs.get("dealName") or "")
        or scenario.scenario_name
    )

    memo_bytes = memo_service.build_memo(
        deal_name=deal_name,
        scenario_name=scenario.scenario_name,
        inputs=inputs,
        outputs=metrics,
        debt=debt,
        sources_and_uses=sources_and_uses,
        sensitivity=stored.get("sensitivity"),
        benchmark_flags=benchmark_flags,
        limitations_text=payload.limitationsText,
    )
    filename = f"IC Memo - {deal_name} - {scenario.scenario_name}.docx"
    return Response(
        content=memo_bytes,
        media_type=DOCX_MEDIA_TYPE,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    db.delete(scenario)
    db.commit()
    return {"deleted": True}
