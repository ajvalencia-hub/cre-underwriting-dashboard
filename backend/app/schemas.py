from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SheetMeta(BaseModel):
    name: str
    maxRow: int
    maxCol: int


class NamedRangeMeta(BaseModel):
    name: str
    sheet: str
    ref: str


class TemplateSummary(BaseModel):
    id: str
    filename: str
    fileHash: str
    createdAt: datetime
    sheets: list[SheetMeta]
    namedRanges: list[NamedRangeMeta]
    reused: bool = False

    model_config = {"from_attributes": True}


class GridCell(BaseModel):
    ref: str
    value: str | float | int | bool | None
    isFormula: bool
    numberFormat: str = "General"


class SheetGrid(BaseModel):
    sheet: str
    columns: list[str]
    rows: list[list[GridCell]]
    totalRows: int
    totalCols: int
    startRow: int = 1


class MappingEntry(BaseModel):
    target: Literal["namedRange", "cell", "table"]
    ref: str | None = None
    anchor: str | None = None
    sheet: str | None = None
    columnOrder: list[str] | None = None
    source: Literal["auto", "manual"] = "manual"


class MappingProfileIn(BaseModel):
    templateId: str
    profileName: str
    mappings: dict[str, MappingEntry]


class MappingProfileOut(BaseModel):
    id: str
    templateId: str
    profileName: str
    mappings: dict[str, MappingEntry]
    unmappedRequiredFields: list[str]
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


class AutoMatchResult(BaseModel):
    mappings: dict[str, MappingEntry]


class GenerateRequest(BaseModel):
    templateId: str
    mappingProfileId: str
    values: dict[str, Any]
    recalc: bool = False


class SensitivityDriver(BaseModel):
    fieldId: str
    values: list[float]


class SensitivityRequest(BaseModel):
    # mode 'native' sweeps the built-in engine (no template needed);
    # 'template' is the original openpyxl+LibreOffice path.
    mode: Literal["native", "template"] = "template"
    templateId: str | None = None
    mappingProfileId: str | None = None
    baseValues: dict[str, Any]
    drivers: list[SensitivityDriver]
    outputFieldIds: list[str]


class SensitivityPoint(BaseModel):
    driverValues: dict[str, float]
    outputs: dict[str, Any]
    warnings: list[str]


class SensitivityResponse(BaseModel):
    points: list[SensitivityPoint]


class DealIn(BaseModel):
    name: str
    inputs: dict[str, Any] = {}


# Deal pipeline stages — single source of truth is input_schema.json's
# `dealStages` (acquisition vs development flows share it with the frontend).
# The stored status column accepts the UNION so a deal that changes type
# never has an invalid status; each board's UI constrains to its own set.
def _load_deal_stages() -> dict[str, list[str]]:
    import json
    from app.config import INPUT_SCHEMA_PATH

    return json.loads(INPUT_SCHEMA_PATH.read_text(encoding="utf-8"))["dealStages"]


DEAL_STAGES_BY_TYPE = _load_deal_stages()
DEAL_STATUSES = tuple(
    dict.fromkeys(stage for stages in DEAL_STAGES_BY_TYPE.values() for stage in stages)
)


class DealUpdate(BaseModel):
    # All-optional partial update: autosave PUTs only the inputs blob, the
    # switcher PUTs only the name, template selection PUTs only the ids.
    name: str | None = None
    inputs: dict[str, Any] | None = None
    status: str | None = None
    activeTemplateId: str | None = None
    activeMappingProfileId: str | None = None

    @field_validator("status")
    @classmethod
    def _status_in_registry(cls, value: str | None) -> str | None:
        if value is not None and value not in DEAL_STATUSES:
            raise ValueError(
                f"Unknown deal status '{value}' — expected one of {DEAL_STATUSES}"
            )
        return value


class DealOut(BaseModel):
    id: str
    name: str
    inputs: dict[str, Any]
    # Declared as the stage registry for the API contract; not enforced on
    # output (every write is validated, and a stray legacy value must still
    # load rather than fail the response).
    status: str = Field("screening", json_schema_extra={"enum": list(DEAL_STATUSES)})
    activeTemplateId: str | None
    activeMappingProfileId: str | None
    createdAt: datetime
    updatedAt: datetime


class ScenarioIn(BaseModel):
    scenarioName: str
    kind: Literal["quickscreen", "full"] = "full"
    dealId: str | None = None
    templateId: str | None = None
    mappingProfileId: str | None = None
    inputs: dict[str, Any]
    # Snapshot of computed results at save time, shaped
    # {"metrics": {...}, "debt": {...}, "sensitivity": {...}} â€” feeds the IC
    # memo's stored-outputs fallback.
    outputs: dict[str, Any] | None = None


class ScenarioUpdate(BaseModel):
    # Unlike ScenarioIn, kind has no default here: an update that omits kind
    # means "keep the stored kind", which must be distinguishable from an
    # explicit (rejected) attempt to change it.
    scenarioName: str
    kind: Literal["quickscreen", "full"] | None = None
    dealId: str | None = None
    templateId: str | None = None
    mappingProfileId: str | None = None
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None


class ScenarioOut(BaseModel):
    id: str
    scenarioName: str
    kind: Literal["quickscreen", "full"]
    dealId: str | None
    sensitivity: dict[str, Any] | None = None
    monteCarlo: dict[str, Any] | None = None
    templateId: str | None
    mappingProfileId: str | None
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    createdAt: datetime
    updatedAt: datetime

    model_config = {"from_attributes": True}


class MarketComp(BaseModel):
    name: str
    submarket: str
    type: Literal["sale", "lease"]
    date: str
    pricePerUnit: float
    priceUnitLabel: str
    capRate: float


class MarketPricingTrends(BaseModel):
    capRateLow: float
    capRateHigh: float
    priceLow: float
    priceHigh: float
    priceUnitLabel: str


class MarketRentTrends(BaseModel):
    rentGrowthYoY: float
    vacancyPct: float


class MarketContextMeta(BaseModel):
    dataSource: str
    note: str


class MarketContextResponse(BaseModel):
    market: str
    submarket: str
    assetClass: str
    location: dict[str, Any]
    comps: list[MarketComp]
    pricingTrends: MarketPricingTrends
    rentTrends: MarketRentTrends
    # Real-data sections vary by which free API keys are configured, so they're
    # loosely typed dicts (always includes at least "dataSource", plus either
    # the real fields or a "note" explaining why it's unavailable) rather than
    # strict models â€” see app/services/data_sources/.
    demographics: dict[str, Any]
    laborMarket: dict[str, Any]
    housing: dict[str, Any]
    macro: dict[str, Any]
    siteRisk: dict[str, Any]
    meta: MarketContextMeta


class DocumentSummary(BaseModel):
    id: str
    filename: str
    fileHash: str
    fileExt: str
    documentType: Literal["offering_memorandum", "rent_roll", "t12_operating_statement", "other"]
    typeConfidence: float
    typeSource: Literal["heuristic", "llm", "manual"]
    typeRationale: str
    createdAt: datetime
    # True when an upload deduplicated onto an existing record (same content
    # hash, possibly a different filename) â€” audit L2: never silent.
    reused: bool = False

    model_config = {"from_attributes": True}


class DocumentTypeUpdate(BaseModel):
    documentType: Literal["offering_memorandum", "rent_roll", "t12_operating_statement", "other"]


class ExtractionRequest(BaseModel):
    documentIds: list[str]


class ApiModel(BaseModel):
    """Base for response models describing structures built as plain dicts:
    extra keys are kept (a response model must never silently drop a field
    the UI reads), while the declared ones document the API contract
    (roadmap #22)."""

    # Fields with defaults are still always present in a response — say so
    # in the schema, so generated types don't mark them optional.
    model_config = {"extra": "allow", "json_schema_serialization_defaults_required": True}


class ProposedUnitMixRow(ApiModel):
    unitType: str
    unitCount: float | None = None
    avgSf: float | None = None
    inPlaceRent: float | None = None
    marketRent: float | None = None
    occupiedCount: float | None = None
    occupancyPct: float | None = None
    sourceRowCount: float | None = None


class UnitMixProposal(ApiModel):
    rows: list[ProposedUnitMixRow]
    groupedBy: Literal["label", "bedBath"]
    warnings: list[str]


class ProposedLeaseRow(ApiModel):
    tenant: str
    suiteId: str
    sf: float | None = None
    startDate: str | None = None
    endDate: str | None = None
    baseRentPsfAnnual: float | None = None
    escalationType: str
    escalationValue: float
    escalationMonths: float
    recoveryType: str
    recoveryValue: float
    freeRentMonths: float

    @field_validator("startDate", "endDate", mode="before")
    @classmethod
    def _iso_date(cls, value):
        return value.isoformat() if hasattr(value, "isoformat") else value


class CommercialLeaseProposal(ApiModel):
    rows: list[ProposedLeaseRow]
    warnings: list[str]


def _enum(default: str, values: list[str]):
    """A string documented as one of `values` in the API schema but not
    enforced on output (stored rows predate some values)."""
    return Field(default, json_schema_extra={"enum": values})


class SourceRefOut(ApiModel):
    doc: str | None = None
    page: float | None = None
    sheet: str | None = None
    cell: str | None = None
    row: float | None = None


class ExtractedFieldOut(ApiModel):
    value: Any = None
    sourceRef: SourceRefOut = Field(default_factory=SourceRefOut)
    confidence: float = 0.0
    source: str = _enum("deterministic", ["deterministic", "llm"])
    rawText: str | None = None
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _wrap_bare_value(cls, data):
        # Older/derived entries can be a bare value rather than a record.
        return data if isinstance(data, dict) else {"value": data}


class UnmatchedExtractionOut(ApiModel):
    suggestedLabel: str = ""
    value: Any = None
    rawText: str | None = None
    sourceRef: SourceRefOut = Field(default_factory=SourceRefOut)
    confidence: float = 0.0


class CrossValidationCheckOut(ApiModel):
    rule: str = ""
    status: str = _enum("pass", ["pass", "warn", "fail"])
    severity: str = _enum("info", ["error", "warning", "info"])
    detail: str = ""
    relatedFieldIds: list[str] = Field(default_factory=list)


class ExtractionResultOut(BaseModel):
    id: str
    documentIds: list[str]
    fields: dict[str, ExtractedFieldOut]
    unitMixProposal: UnitMixProposal | None = None
    commercialLeaseProposal: CommercialLeaseProposal | None = None
    unmatched: list[UnmatchedExtractionOut]
    crossValidation: list[CrossValidationCheckOut]
    warnings: list[str]
    confirmedValues: dict[str, Any]
    confirmedAt: datetime | None
    createdAt: datetime

    model_config = {"from_attributes": True}


class ExtractionConfirmRequest(BaseModel):
    confirmedValues: dict[str, Any]
