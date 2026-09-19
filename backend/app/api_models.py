"""Response models for routes that build plain dicts (roadmap #22).

They describe the API contract in the OpenAPI schema (and so in the
frontend's generated types) without changing any response: every model
keeps undeclared keys (ApiModel extra="allow"), and only fields the UI
treats as always present are declared. Keys a route adds only sometimes
(e.g. compute's gpEconomics) stay undeclared, so no response gains a null
it didn't have.
"""

from datetime import datetime
from typing import Any, Literal

from app.schemas import ApiModel, DealOut, _enum


# ---- deals: attachments, notes, history, metrics --------------------------
class AttachmentOut(ApiModel):
    id: str
    filename: str
    fileHash: str
    fileExt: str
    sizeBytes: int | None
    source: str = _enum("attachment", ["attachment", "extraction"])
    documentType: str
    createdAt: datetime


class NoteOut(ApiModel):
    id: str
    body: str
    createdAt: datetime
    updatedAt: datetime


class SnapshotMetaOut(ApiModel):
    id: str
    kind: str = _enum("autosave", ["baseline", "autosave", "restore", "agent"])
    changedPaths: list[str]
    createdAt: datetime
    updatedAt: datetime


class DealMetricsOk(ApiModel):
    status: Literal["ok"]
    totalCost: float | None
    equity: float | None
    leveredIrr: float | None
    equityMultiple: float | None
    yieldOnCost: float | None
    goingInCapRate: float | None


class DealMetricsIncomplete(ApiModel):
    status: Literal["incomplete"]
    missing: list[str]


# ---- presets ---------------------------------------------------------------
class PresetOut(ApiModel):
    id: str
    name: str
    description: str
    values: dict[str, Any]
    source: str = _enum("user", ["user", "seed"])
    createdAt: datetime
    updatedAt: datetime


# ---- backups ---------------------------------------------------------------
class BackupSnapshotOut(ApiModel):
    name: str
    createdAt: str | None
    uploadCount: int
    hasDb: bool


class AutomaticBackupStatusOut(ApiModel):
    at: str
    ok: bool
    result: str | None
    error: str | None


class BackupListingOut(ApiModel):
    daily: list[BackupSnapshotOut]
    weekly: list[BackupSnapshotOut]
    pre_restore: list[BackupSnapshotOut]
    pre_migration: list[BackupSnapshotOut]
    lastAutomatic: AutomaticBackupStatusOut | None


# ---- compute ---------------------------------------------------------------
class DebtStressCellOut(ApiModel):
    rateBumpBps: float
    noiHaircutPct: float
    dscr: float | None
    refiProceeds: float
    governingConstraint: str
    refiShortfall: float


class DebtBlockOut(ApiModel):
    loanAmount: float
    sizedLoanAmount: float
    governingConstraint: str
    candidates: dict[str, float]
    sizingNoi: float
    value: float
    stress: list[DebtStressCellOut]


class ComputeResponseOut(ApiModel):
    outputs: dict[str, float | str]
    warnings: list[str]
    debt: DebtBlockOut | None
    irrConvention: str = _enum("periodic_monthly", ["periodic_monthly", "xirr"])
    waterfallStyle: str = _enum("european", ["european", "american"])


# ---- admin -----------------------------------------------------------------
class IntegrationStatusOut(ApiModel):
    envVar: str
    label: str
    configured: bool
    purpose: str


class LibreOfficeStatusOut(ApiModel):
    available: bool
    path: str | None
    enables: list[str]


class OcrStatusOut(ApiModel):
    available: bool
    enables: list[str]


class ExternalToolsOut(ApiModel):
    libreoffice: LibreOfficeStatusOut
    ocr: OcrStatusOut


# ---- portfolio -------------------------------------------------------------
class PortfolioTotalsOut(ApiModel):
    equity: float
    totalCost: float
    units: float
    sf: float


class PortfolioStatusBucketOut(PortfolioTotalsOut):
    status: str
    count: int


class PortfolioTypeBucketOut(PortfolioTotalsOut):
    dealType: str
    count: int


class MarketExposureOut(ApiModel):
    market: str
    equity: float


class ClassExposureOut(ApiModel):
    assetClass: str
    equity: float


class ConcentrationOut(ApiModel):
    market: str
    equity: float
    sharePct: float


class PortfolioDealOut(ApiModel):
    id: str
    name: str
    status: str
    dealType: str
    market: str
    assetClass: str
    equity: float
    leveredIrr: float | None
    equityMultiple: float | None


class PortfolioExcludedOut(ApiModel):
    id: str
    name: str
    reason: str


class PortfolioOut(ApiModel):
    dealCount: int
    excludedCount: int
    totals: PortfolioTotalsOut
    byStatus: list[PortfolioStatusBucketOut]
    byDealType: list[PortfolioTypeBucketOut]
    exposureByMarket: list[MarketExposureOut]
    exposureByAssetClass: list[ClassExposureOut]
    blendedLeveredIrr: float | None
    blendedEquityMultiple: float | None
    concentration: list[ConcentrationOut]
    deals: list[PortfolioDealOut]
    excluded: list[PortfolioExcludedOut]


# ---- search ----------------------------------------------------------------
class SearchItemOut(ApiModel):
    id: str
    title: str
    subtitle: str


class SearchGroupOut(ApiModel):
    kind: str = _enum("deals", ["deals", "tenants", "comps", "notes"])
    items: list[SearchItemOut]


class SearchOut(ApiModel):
    query: str
    groups: list[SearchGroupOut]


# ---- compute side tools ------------------------------------------------------
class HoldSweepRowOut(ApiModel):
    holdYear: float
    unleveredIrr: float | None
    leveredIrr: float | None
    equityMultiple: float | None
    netProceeds: float | None


class HoldSweepOut(ApiModel):
    rows: list[HoldSweepRowOut]
    modeledHoldYears: float
    warnings: list[str]


class RefiVsSaleSideOut(ApiModel):
    holdYears: float
    leveredIrr: float | None
    equityMultiple: float | None


class RefiVsSaleOut(ApiModel):
    saleAtStabilization: RefiVsSaleSideOut | None
    holdThroughRefi: RefiVsSaleSideOut | None
    warnings: list[str]


class HoldSweepResponseOut(ApiModel):
    sweep: HoldSweepOut
    refiVsSale: RefiVsSaleOut


class TornadoBarOut(ApiModel):
    key: str
    label: str
    low: float | None
    high: float | None
    impact: float
    # Run 6: an input that cannot move the metric for this deal (e.g. a
    # lease-up input on a stabilized deal) is flagged, with the reason.
    inert: bool = False
    reason: str | None = None


class TornadoOut(ApiModel):
    metric: str
    base: float
    bars: list[TornadoBarOut]


class GoalSeekInputOut(ApiModel):
    id: str
    label: str
    type: str


class GoalSeekOut(ApiModel):
    solvedValue: float | None
    scannedRange: tuple[float, float]
    targetInput: str
    outputMetric: str
    targetValue: float
    tolerance: float


# ---- templates / mapping -----------------------------------------------------
class MappingPreviewRowOut(ApiModel):
    fieldId: str
    isOutput: bool
    hasValue: bool
    status: str = _enum(
        "unmapped",
        ["ok", "unitWarning", "blank", "formula", "multiCell", "unresolved", "tableSkips", "unmapped", "output"],
    )
    resolvedRef: str | None


class MappingPreviewOut(ApiModel):
    fields: list[MappingPreviewRowOut]


class RecalcAgreementRowOut(ApiModel):
    fieldId: str
    excelValue: str | float | bool | None
    libreOfficeValue: str | float | bool | None
    agrees: bool


class RecalcAgreementOut(ApiModel):
    status: str = _enum("agrees", ["agrees", "differs", "noOutputsMapped", "noSavedValues"])
    rows: list[RecalcAgreementRowOut]


# ---- comps -------------------------------------------------------------------
class CompOut(ApiModel):
    id: str
    kind: str = _enum("sale", ["sale", "rent"])
    name: str
    address: str
    market: str
    submarket: str
    propertyType: str
    source: str
    notes: str
    createdAt: datetime


class CompsImportOut(ApiModel):
    phase: str = _enum("preview", ["preview", "imported"])
    imported: int
    warnings: list[str]


class CompMapPointOut(ApiModel):
    id: str
    name: str
    lat: float
    lon: float


class CompMapOut(ApiModel):
    points: list[CompMapPointOut]
    warnings: list[str]


# ---- Monte Carlo / market ------------------------------------------------------
class MonteCarloJobOut(ApiModel):
    status: str = _enum("running", ["running", "done", "failed", "cancelled"])
    completed: int
    n: int


class MonteCarloCancelOut(ApiModel):
    jobId: str
    status: str = _enum("cancelling", ["cancelling", "cancelled", "done", "failed"])


class MarketRatesOut(ApiModel):
    dataSource: str
    rates: dict[str, float | None]


# ---- investment committee (roadmap #28) ------------------------------------
IcState = Literal["draft", "submitted", "approved", "rejected"]
IcKind = Literal["submit", "approve", "reject", "return", "reopen", "comment"]


class IcEventOut(ApiModel):
    id: str
    kind: IcKind
    actor: str
    comment: str
    requiredApprovals: int | None
    hasSnapshot: bool
    createdAt: str


class IcSubmissionOut(ApiModel):
    eventId: str
    submittedBy: str
    submittedAt: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    # False once the deal was returned or reopened after this submission.
    current: bool


class IcSummaryOut(ApiModel):
    state: IcState
    locked: bool
    requiredApprovals: int | None
    approvers: list[str]
    lastSubmission: IcSubmissionOut | None
    events: list[IcEventOut]


# ---- auth (optional CRE_API_TOKEN gate) --------------------------------------
class AuthStatusOut(ApiModel):
    required: bool
    authenticated: bool


# ---- deals: bulk tags ----------------------------------------------------------
class BulkTagsOut(ApiModel):
    updated: list[DealOut]
    missing: list[str]


# ---- Underwriting Agent ----------------------------------------------------------
class AgentToolCallLogOut(ApiModel):
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    privilege: str = _enum("read", ["read", "write", "unknown"])


class AgentUnverifiedClaimOut(ApiModel):
    raw: str
    value: float
    kind: str = _enum("bare", ["dollar", "percent", "multiple", "bare"])


class AgentMessageOut(ApiModel):
    id: str
    role: str = _enum("user", ["user", "assistant"])
    content: str
    toolCalls: list[AgentToolCallLogOut]
    proposalIds: list[str]
    unverifiedClaims: list[AgentUnverifiedClaimOut]
    stoppedReason: str | None
    createdAt: datetime


class AgentTurnProposalOut(ApiModel):
    """A proposal as a turn returns it (no createdAt — see AgentProposalOut)."""

    id: str
    kind: str = _enum("input_changes", ["input_changes", "scenario"])
    changes: dict[str, Any]
    rationale: str
    scenarioName: str | None
    preview: dict[str, Any] | None
    warnings: list[str]
    status: str = _enum("pending", ["pending", "approved", "rejected", "stale"])


class AgentProposalOut(AgentTurnProposalOut):
    createdAt: datetime


class AgentThreadOut(ApiModel):
    id: str
    dealId: str
    provider: str
    totalInputTokens: int
    totalOutputTokens: int
    messages: list[AgentMessageOut]
    proposals: list[AgentProposalOut]


class AgentThreadRefOut(ApiModel):
    id: str
    dealId: str
    provider: str


class AgentPlayOut(ApiModel):
    id: str
    label: str


class AgentProviderOut(ApiModel):
    id: str
    label: str
    hasKey: bool


class AgentTurnOut(ApiModel):
    threadId: str
    text: str
    toolCalls: list[AgentToolCallLogOut]
    proposals: list[AgentTurnProposalOut]
    unverifiedClaims: list[AgentUnverifiedClaimOut]
    stoppedReason: str | None


class AgentApproveOut(ApiModel):
    deal: DealOut
    proposal: AgentProposalOut


class AgentRejectOut(ApiModel):
    proposal: AgentProposalOut
