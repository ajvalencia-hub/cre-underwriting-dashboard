from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


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


class SheetGrid(BaseModel):
    sheet: str
    columns: list[str]
    rows: list[list[GridCell]]
    totalRows: int
    totalCols: int


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


DEAL_STATUSES = ("screening", "underwriting", "loi", "under_contract", "closed", "dead")


class DealUpdate(BaseModel):
    # All-optional partial update: autosave PUTs only the inputs blob, the
    # switcher PUTs only the name, template selection PUTs only the ids.
    name: str | None = None
    inputs: dict[str, Any] | None = None
    status: Literal["screening", "underwriting", "loi", "under_contract", "closed", "dead"] | None = None
    activeTemplateId: str | None = None
    activeMappingProfileId: str | None = None


class DealOut(BaseModel):
    id: str
    name: str
    inputs: dict[str, Any]
    status: str = "screening"
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
    # {"metrics": {...}, "debt": {...}, "sensitivity": {...}} — feeds the IC
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
    # strict models — see app/services/data_sources/.
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
    dealId: str | None = None
    documentType: Literal["offering_memorandum", "rent_roll", "t12_operating_statement", "other"]
    typeConfidence: float
    typeSource: Literal["heuristic", "llm", "manual"]
    typeRationale: str
    createdAt: datetime
    # True when an upload deduplicated onto an existing record (same content
    # hash, possibly a different filename) — audit L2: never silent.
    reused: bool = False

    model_config = {"from_attributes": True}


class DocumentTypeUpdate(BaseModel):
    documentType: Literal["offering_memorandum", "rent_roll", "t12_operating_statement", "other"]


class ExtractionRequest(BaseModel):
    documentIds: list[str]


class ExtractionResultOut(BaseModel):
    id: str
    documentIds: list[str]
    fields: dict[str, Any]
    unitMixProposal: dict[str, Any] | None = None
    commercialLeaseProposal: dict[str, Any] | None = None
    unmatched: list[Any]
    crossValidation: list[Any]
    warnings: list[str]
    confirmedValues: dict[str, Any]
    confirmedAt: datetime | None
    createdAt: datetime

    model_config = {"from_attributes": True}


class ExtractionConfirmRequest(BaseModel):
    confirmedValues: dict[str, Any]
