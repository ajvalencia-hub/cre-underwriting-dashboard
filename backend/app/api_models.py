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

from app.schemas import ApiModel, _enum


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
    kind: str = _enum("autosave", ["baseline", "autosave", "restore"])
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
