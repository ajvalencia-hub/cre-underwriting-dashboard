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


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_name: Mapped[str] = mapped_column(String)
    template_id: Mapped[str] = mapped_column(String, index=True)
    mapping_profile_id: Mapped[str] = mapped_column(String, index=True)
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String)
    file_hash: Mapped[str] = mapped_column(String, index=True)
    stored_path: Mapped[str] = mapped_column(String)
    file_ext: Mapped[str] = mapped_column(String)
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
    unmatched: Mapped[list] = mapped_column(JSON, default=list)
    cross_validation: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_values: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
