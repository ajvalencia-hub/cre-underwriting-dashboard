"""Property-tax lookup endpoint (H4).

The router is a pure consumer: the reassessment projection comes from
proforma.operations so the formula lives in exactly one place.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import property_tax
from app.services.proforma.operations import (
    DEFAULT_ASSESSMENT_RATIO,
    projected_reassessed_taxes,
)

router = APIRouter(prefix="/api/property-tax", tags=["property-tax"])


class PropertyTaxLookupRequest(BaseModel):
    query: str
    county: str | None = None
    purchasePrice: float | None = None
    assessmentRatio: float | None = None


@router.get("/counties")
def list_counties():
    return [
        {"id": county, "label": adapter.JURISDICTION}
        for county, adapter in property_tax.ADAPTERS.items()
    ]


@router.post("/lookup")
def lookup(req: PropertyTaxLookupRequest):
    result = property_tax.lookup(req.query, req.county)
    projection = None
    millage = result.get("millageRate")
    if req.purchasePrice and req.purchasePrice > 0 and millage:
        ratio = req.assessmentRatio or DEFAULT_ASSESSMENT_RATIO
        projected_ad_valorem = projected_reassessed_taxes(
            req.purchasePrice, ratio, millage
        )
        # I5: non-ad-valorem assessments don't reprice at sale — they carry
        # into the projection unchanged.
        carried_nav = result.get("nonAdValorem") or 0.0
        projection = {
            "assessmentRatio": ratio,
            "projectedAssessedValue": req.purchasePrice * ratio,
            "projectedAdValorem": projected_ad_valorem,
            "carriedNonAdValorem": carried_nav,
            "projectedAnnualTaxes": projected_ad_valorem + carried_nav,
        }
    return {**result, "projection": projection}
