from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Scenario, Template
from app.schemas import ScenarioIn, ScenarioOut, ScenarioUpdate

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _to_out(scenario: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=scenario.id,
        scenarioName=scenario.scenario_name,
        kind=scenario.kind,
        templateId=scenario.template_id,
        mappingProfileId=scenario.mapping_profile_id,
        inputs=scenario.inputs,
        outputs=scenario.outputs,
        createdAt=scenario.created_at,
        updatedAt=scenario.updated_at,
    )


@router.get("", response_model=list[ScenarioOut])
def list_scenarios(
    template_id: str | None = None, kind: str | None = None, db: Session = Depends(get_db)
):
    stmt = select(Scenario)
    if template_id:
        stmt = stmt.where(Scenario.template_id == template_id)
    if kind:
        stmt = stmt.where(Scenario.kind == kind)
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
        template_id=payload.templateId,
        mapping_profile_id=payload.mappingProfileId,
        inputs=payload.inputs,
        outputs={},
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
    scenario.template_id = payload.templateId
    scenario.mapping_profile_id = payload.mappingProfileId
    scenario.inputs = payload.inputs
    db.commit()
    db.refresh(scenario)
    return _to_out(scenario)


@router.delete("/{scenario_id}")
def delete_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(404, "Scenario not found")
    db.delete(scenario)
    db.commit()
    return {"deleted": True}
