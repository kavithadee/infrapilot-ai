from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.db import Base


# ---------------------------------------------------------------------------
# Core tables
# ---------------------------------------------------------------------------

class Incident(Base):
    __tablename__ = "incidents"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    title        = Column(Text, nullable=False)
    description  = Column(Text, nullable=False)
    service_name = Column(Text)
    severity     = Column(String(20), default="high")   # critical/high/medium/low
    status       = Column(String(20), default="open")   # open/investigating/resolved
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InvestigationRun(Base):
    __tablename__ = "investigation_runs"

    id                = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    incident_id       = Column(UUID(as_uuid=True), ForeignKey("incidents.id"), nullable=False)
    status            = Column(String(20), default="pending")  # pending/running/completed/failed
    started_at        = Column(DateTime(timezone=True))
    completed_at      = Column(DateTime(timezone=True))
    agent_model       = Column(Text)
    final_summary     = Column(Text)
    likely_root_cause = Column(Text)
    confidence_score  = Column(Float)
    report_json       = Column(JSON)   # Full InvestigationReport stored here
    error_message     = Column(Text)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id        = Column(UUID(as_uuid=True), ForeignKey("investigation_runs.id"), nullable=False)
    tool_name     = Column(Text, nullable=False)
    input_json    = Column(JSON, nullable=False)
    output_json   = Column(JSON)
    latency_ms    = Column(Integer)
    cache_hit     = Column(Boolean, default=False)
    status        = Column(String(20), default="success")  # success/error
    error_message = Column(Text)
    sequence_num  = Column(Integer)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Simulation tables (seeded, queried by tools)
# ---------------------------------------------------------------------------

class SimulatedDeploy(Base):
    __tablename__ = "simulated_deploys"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    service_name   = Column(Text, nullable=False)
    version        = Column(Text, nullable=False)
    deployed_at    = Column(DateTime(timezone=True), nullable=False)
    author         = Column(Text)
    commit_sha     = Column(Text)
    changed_files  = Column(JSON)   # list[str]
    config_changes = Column(JSON)   # dict
    status         = Column(Text)   # success/failed/rollback


class SimulatedLog(Base):
    __tablename__ = "simulated_logs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    service_name = Column(Text, nullable=False)
    timestamp    = Column(DateTime(timezone=True), nullable=False)
    severity     = Column(Text)    # INFO/WARN/ERROR/CRITICAL
    message      = Column(Text, nullable=False)
    meta         = Column(JSON)    # renamed from 'metadata' — reserved by SQLAlchemy


class SimulatedK8sStatus(Base):
    __tablename__ = "simulated_k8s_status"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    service_name = Column(Text, nullable=False)
    pod_name     = Column(Text)
    pod_status   = Column(Text)    # Running/CrashLoopBackOff/Pending
    restarts     = Column(Integer, default=0)
    last_event   = Column(Text)
    recorded_at  = Column(DateTime(timezone=True), nullable=False)


class SimulatedBqError(Base):
    __tablename__ = "simulated_bq_errors"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_name = Column(Text, nullable=False)
    timestamp  = Column(DateTime(timezone=True), nullable=False)
    error_type = Column(Text)   # AUTH_ERROR/SCHEMA_ERROR/PERMISSION_DENIED
    message    = Column(Text)
    count      = Column(Integer, default=1)


class SimulatedConfigDiff(Base):
    __tablename__ = "simulated_config_diffs"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    service_name = Column(Text, nullable=False)
    deploy_id    = Column(Text)   # version string e.g. "v42"
    diff_json    = Column(JSON)   # { added: [...], removed: [...], changed: [...] }
    recorded_at  = Column(DateTime(timezone=True), nullable=False)
