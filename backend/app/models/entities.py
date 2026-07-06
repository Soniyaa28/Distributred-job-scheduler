import enum
import uuid
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

def now() -> datetime: return datetime.now(timezone.utc)

class JobStatus(str, enum.Enum):
    scheduled="scheduled"; queued="queued"; running="running"; succeeded="succeeded"; failed="failed"; dead="dead"; cancelled="cancelled"
class RetryStrategy(str, enum.Enum):
    fixed="fixed"; linear="linear"; exponential="exponential"
class WorkerStatus(str, enum.Enum):
    online="online"; offline="offline"; draining="draining"

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

class User(TimestampMixin, Base):
    __tablename__="users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Project(TimestampMixin, Base):
    __tablename__="projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str|None] = mapped_column(Text)
    __table_args__=(UniqueConstraint("owner_id","name"),)

class Queue(TimestampMixin, Base):
    __tablename__="queues"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=10)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__=(UniqueConstraint("project_id","name"),)

class Job(TimestampMixin, Base):
    __tablename__="jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    payload: Mapped[dict[str,Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    cron_expression: Mapped[str|None] = mapped_column(String(100))
    next_run_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True), index=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_strategy: Mapped[RetryStrategy] = mapped_column(Enum(RetryStrategy), default=RetryStrategy.exponential)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=30)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    idempotency_key: Mapped[str|None] = mapped_column(String(200))
    claimed_by: Mapped[uuid.UUID|None] = mapped_column(ForeignKey("workers.id", ondelete="SET NULL"))
    claimed_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str,Any]|None] = mapped_column(JSONB)
    last_error: Mapped[str|None] = mapped_column(Text)
    parent_job_id: Mapped[uuid.UUID|None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    __table_args__=(UniqueConstraint("queue_id","idempotency_key"), Index("ix_jobs_claim", "queue_id","status","scheduled_at","priority"))

class Worker(TimestampMixin, Base):
    __tablename__="workers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[WorkerStatus] = mapped_column(Enum(WorkerStatus), default=WorkerStatus.online)
    queues: Mapped[list[str]] = mapped_column(JSONB, default=list)
    metadata_: Mapped[dict[str,Any]] = mapped_column("metadata", JSONB, default=dict)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    __table_args__=(UniqueConstraint("project_id","name"),)

class JobExecution(Base):
    __tablename__="job_executions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[uuid.UUID|None] = mapped_column(ForeignKey("workers.id", ondelete="SET NULL"))
    attempt: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.running)
    error: Mapped[str|None] = mapped_column(Text)
    result: Mapped[dict[str,Any]|None] = mapped_column(JSONB)
