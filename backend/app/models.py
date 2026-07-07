import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String)
    file_hash: Mapped[str] = mapped_column(String, index=True)
    stored_path: Mapped[str] = mapped_column(String)
    sheets: Mapped[list] = mapped_column(JSON, default=list)
    named_ranges: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MappingProfile(Base):
    __tablename__ = "mapping_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(String, index=True)
    profile_name: Mapped[str] = mapped_column(String)
    mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    # The full Deal Inputs form values, plus a "quickScreen" key holding the
    # Quick Screen inputs — one JSON blob per deal, autosaved from the client.
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    # Pipeline stage (H7): screening | underwriting | loi | under_contract |
    # closed | dead. Existing deals migrate to "screening".
    status: Mapped[str] = mapped_column(String, default="screening")
    active_template_id: Mapped[str | None] = mapped_column(String, nullable=True)
    active_mapping_profile_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_name: Mapped[str] = mapped_column(String)
    # Nullable for legacy rows created before deals existed; the startup
    # migration backfills them onto a "Default Deal".
    deal_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # "full" scenarios are tied to a template + mapping profile (existing Deal
    # Inputs flow). "quickscreen" scenarios store raw QuickScreenInputs and have
    # neither, since the back-of-napkin screen doesn't require a template.
    kind: Mapped[str] = mapped_column(String, default="full")
    template_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    mapping_profile_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    # Last saved sensitivity run ({description, header, rows, run}) — feeds
    # the memo's sensitivity section and the comparison tooling.
    sensitivity: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DealSnapshot(Base):
    """Input change history (H9). Each row is a checkpoint of the deal's full
    inputs AFTER a save; changed_paths lists what moved since the previous
    checkpoint (dotted one level into dict values, e.g. quickScreen.rent).
    Saves within a 10-minute window coalesce into the newest row."""

    __tablename__ = "deal_snapshots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(String, index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    changed_paths: Mapped[list] = mapped_column(JSON, default=list)
    # baseline (pre-first-edit state) | autosave | restore
    kind: Mapped[str] = mapped_column(String, default="autosave")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AssumptionPreset(Base):
    """Named bundle of assumption field values (H8). `values` maps input
    schema field ids -> values; applying is a client-side, user-confirmed
    merge (preview diff first), never automatic."""

    __tablename__ = "assumption_presets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(String, default="")
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String, default="user")  # user | seed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class SaleComp(Base):
    """Sale comparable (H5) — global, not deal-scoped, filtered by market at
    query time. Dollar/date fields nullable: comps arrive incomplete from
    CSV imports and a partial comp is still useful context."""

    __tablename__ = "sale_comps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String, default="")
    market: Mapped[str] = mapped_column(String, default="", index=True)
    submarket: Mapped[str] = mapped_column(String, default="")
    property_type: Mapped[str] = mapped_column(String, default="")
    sale_date: Mapped[str] = mapped_column(String, default="")  # ISO yyyy-mm-dd or ""
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[float | None] = mapped_column(Float, nullable=True)
    sf: Mapped[float | None] = mapped_column(Float, nullable=True)
    cap_rate_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_built: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | yardi_csv
    notes: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RentComp(Base):
    __tablename__ = "rent_comps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String)
    address: Mapped[str] = mapped_column(String, default="")
    market: Mapped[str] = mapped_column(String, default="", index=True)
    submarket: Mapped[str] = mapped_column(String, default="")
    property_type: Mapped[str] = mapped_column(String, default="")
    as_of: Mapped[str] = mapped_column(String, default="")  # ISO yyyy-mm-dd or ""
    unit_type: Mapped[str] = mapped_column(String, default="")
    avg_rent: Mapped[float | None] = mapped_column(Float, nullable=True)  # $/mo
    avg_sf: Mapped[float | None] = mapped_column(Float, nullable=True)
    occupancy_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    year_built: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String, default="manual")
    notes: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String)
    file_hash: Mapped[str] = mapped_column(String, index=True)
    stored_path: Mapped[str] = mapped_column(String)
    file_ext: Mapped[str] = mapped_column(String)
    # Nullable only for rows created before document-deal scoping landed;
    # every upload from that point on requires one. Without this, every deal
    # sees every OTHER deal's uploads — extraction from deal A silently
    # offers deal B's rent roll as a source.
    deal_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    # offering_memorandum | rent_roll | t12_operating_statement | other
    document_type: Mapped[str] = mapped_column(String)
    type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    type_source: Mapped[str] = mapped_column(String, default="heuristic")  # heuristic | llm | manual
    type_rationale: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    # Proposed grouped unit-mix table for multifamily rent rolls (nullable).
    unit_mix_proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Proposed lease-level rows for commercial rent rolls (H1, nullable).
    commercial_lease_proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    unmatched: Mapped[list] = mapped_column(JSON, default=list)
    cross_validation: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_values: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentThread(Base):
    """K4: one Underwriting Agent conversation, scoped to a single deal.
    Token totals are accumulated here as messages are processed (K10) so no
    later migration is needed to add cost tracking to an already-shipped
    table."""

    __tablename__ = "agent_threads"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    deal_id: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String, default="anthropic")
    total_input_tokens: Mapped[int] = mapped_column(default=0)
    total_output_tokens: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class AgentMessage(Base):
    """K4: one user or assistant turn in a thread. `tool_calls` and
    `proposal_ids` are a transparency log of what happened while producing
    an assistant turn (rendered as expandable chips in K6) — they are not
    replayed back to the provider on the next turn; each new turn only
    re-sends prior user/assistant TEXT, so the model always re-verifies
    figures via a fresh tool call rather than trusting stale tool output
    from earlier in the conversation."""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(String, default="")
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    proposal_ids: Mapped[list] = mapped_column(JSON, default=list)
    unverified_claims: Mapped[list] = mapped_column(JSON, default=list)
    stopped_reason: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentToolCall(Base):
    """K4: one tool invocation during a turn — the full audit trail behind
    an AgentMessage's summarized `tool_calls` log."""

    __tablename__ = "agent_tool_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    message_id: Mapped[str] = mapped_column(String, index=True)
    tool_name: Mapped[str] = mapped_column(String)
    privilege: Mapped[str] = mapped_column(String)  # "read" | "write"
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentProposal(Base):
    """K4: a WRITE tool's output, persisted for user review. Applying one
    still goes through the ordinary PUT /api/deals/{id} (K7) — this row is
    never written to Deal.inputs directly by anything in this module."""

    __tablename__ = "agent_proposals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    deal_id: Mapped[str] = mapped_column(String, index=True)
    tool_call_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # "input_changes" | "scenario"
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(String, default="")
    scenario_name: Mapped[str | None] = mapped_column(String, nullable=True)
    preview: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    # pending | approved | rejected | stale
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
