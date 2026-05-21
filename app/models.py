"""
AVIS Connect — DB Models (connect.* schema)
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, Float,
    ForeignKey, Integer, String, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── Enums ─────────────────────────────────────────────────────────────────────

class PushStatus(str, enum.Enum):
    success = "success"
    error   = "error"
    retrying = "retrying"
    pending  = "pending"


class ConnectorType(str, enum.Enum):
    netsuite    = "netsuite"
    salesforce  = "salesforce"
    darwinbox   = "darwinbox"
    timesheet   = "timesheet"
    generic_rest = "generic_rest"


# ── Tables ────────────────────────────────────────────────────────────────────

class Project(Base):
    """A client project — e.g. rms-tessolve, healthcare-clientx."""
    __tablename__ = "projects"
    __table_args__ = {"schema": "connect"}

    id          : Mapped[int]      = mapped_column(Integer, primary_key=True)
    slug        : Mapped[str]      = mapped_column(String(80), unique=True, nullable=False)
    name        : Mapped[str]      = mapped_column(String(200), nullable=False)
    description : Mapped[str|None] = mapped_column(Text)
    active      : Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at  : Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    connectors  : Mapped[list[ConnectorConfig]] = relationship(back_populates="project", cascade="all, delete-orphan")
    credentials : Mapped[list[Credential]]      = relationship(back_populates="project", cascade="all, delete-orphan")
    push_logs   : Mapped[list[PushLog]]         = relationship(back_populates="project", cascade="all, delete-orphan")
    operations  : Mapped[list[Operation]]       = relationship(back_populates="project", cascade="all, delete-orphan")


class ConnectorConfig(Base):
    """A connector instance for a project — links project to a connector type."""
    __tablename__ = "connectors"
    __table_args__ = {"schema": "connect"}

    id             : Mapped[int]          = mapped_column(Integer, primary_key=True)
    project_id     : Mapped[int]          = mapped_column(ForeignKey("connect.projects.id"))
    connector_type : Mapped[str]          = mapped_column(String(50), nullable=False)
    base_url       : Mapped[str|None]     = mapped_column(String(500))
    active         : Mapped[bool]         = mapped_column(Boolean, default=True)
    created_at     : Mapped[datetime]     = mapped_column(DateTime, server_default=func.now())

    project    : Mapped[Project]       = relationship(back_populates="connectors")
    operations : Mapped[list[Operation]] = relationship(back_populates="connector", cascade="all, delete-orphan")


class Credential(Base):
    """Encrypted credential key-value for a project+connector pair."""
    __tablename__ = "credentials"
    __table_args__ = {"schema": "connect"}

    id              : Mapped[int]      = mapped_column(Integer, primary_key=True)
    project_id      : Mapped[int]      = mapped_column(ForeignKey("connect.projects.id"))
    connector_type  : Mapped[str]      = mapped_column(String(50), nullable=False)
    key             : Mapped[str]      = mapped_column(String(100), nullable=False)
    value_encrypted : Mapped[str]      = mapped_column(Text, nullable=False)
    updated_at      : Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    updated_by      : Mapped[str|None] = mapped_column(String(100))

    project : Mapped[Project] = relationship(back_populates="credentials")


class Operation(Base):
    """An API operation registered for a project+connector."""
    __tablename__ = "operations"
    __table_args__ = {"schema": "connect"}

    id             : Mapped[int]      = mapped_column(Integer, primary_key=True)
    project_id     : Mapped[int]      = mapped_column(ForeignKey("connect.projects.id"))
    connector_id   : Mapped[int]      = mapped_column(ForeignKey("connect.connectors.id"))
    connector_type : Mapped[str]      = mapped_column(String(50), nullable=False)
    operation_name : Mapped[str]      = mapped_column(String(100), nullable=False)
    endpoint       : Mapped[str]      = mapped_column(String(500), nullable=False)
    method         : Mapped[str]      = mapped_column(String(10), default="POST")
    description    : Mapped[str|None] = mapped_column(Text)
    active         : Mapped[bool]     = mapped_column(Boolean, default=True)

    project   : Mapped[Project]         = relationship(back_populates="operations")
    connector : Mapped[ConnectorConfig] = relationship(back_populates="operations")


class PushLog(Base):
    """Full audit log of every execution — payload in, response out, timing."""
    __tablename__ = "push_log"
    __table_args__ = {"schema": "connect"}

    id             : Mapped[int]       = mapped_column(BigInteger, primary_key=True)
    project_id     : Mapped[int]       = mapped_column(ForeignKey("connect.projects.id"))
    project_slug   : Mapped[str]       = mapped_column(String(80), nullable=False)
    connector_type : Mapped[str]       = mapped_column(String(50), nullable=False)
    operation      : Mapped[str]       = mapped_column(String(100), nullable=False)
    payload_json   : Mapped[str|None]  = mapped_column(Text)
    response_json  : Mapped[str|None]  = mapped_column(Text)
    status         : Mapped[str]       = mapped_column(String(20), default="pending")
    http_status    : Mapped[int|None]  = mapped_column(Integer)
    duration_ms    : Mapped[float|None]= mapped_column(Float)
    error_msg      : Mapped[str|None]  = mapped_column(Text)
    retry_count    : Mapped[int]       = mapped_column(Integer, default=0)
    original_log_id: Mapped[int|None]  = mapped_column(BigInteger)  # set on retry
    created_at     : Mapped[datetime]  = mapped_column(DateTime, server_default=func.now())

    project : Mapped[Project] = relationship(back_populates="push_logs")
