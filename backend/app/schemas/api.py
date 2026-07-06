import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models.entities import JobStatus, RetryStrategy, WorkerStatus

class ORM(BaseModel):
    model_config=ConfigDict(from_attributes=True)
class Register(BaseModel):
    email: EmailStr; password: str=Field(min_length=8,max_length=128); full_name: str=Field(min_length=1,max_length=120)
class Login(BaseModel):
    email: EmailStr; password: str
class Token(BaseModel):
    access_token: str; token_type: str="bearer"
class UserOut(ORM):
    id: uuid.UUID; email: EmailStr; full_name: str; is_active: bool; created_at: datetime
class ProjectCreate(BaseModel):
    name: str=Field(min_length=1,max_length=120); description: str|None=None
class ProjectOut(ProjectCreate,ORM):
    id: uuid.UUID; owner_id: uuid.UUID; created_at: datetime; updated_at: datetime
class QueueCreate(BaseModel):
    project_id: uuid.UUID; name: str=Field(min_length=1,max_length=120); concurrency_limit: int=Field(default=10,ge=1,le=10000)
class QueueOut(QueueCreate,ORM):
    id: uuid.UUID; is_paused: bool; created_at: datetime
class QueuePatch(BaseModel):
    name: str|None=Field(default=None,min_length=1,max_length=120); concurrency_limit: int|None=Field(default=None,ge=1); is_paused: bool|None=None
class JobCreate(BaseModel):
    queue_id: uuid.UUID; name: str=Field(min_length=1,max_length=160); payload: dict[str,Any]=Field(default_factory=dict)
    priority: int=Field(default=0,ge=-1000,le=1000); scheduled_at: datetime|None=None; delay_seconds: int|None=Field(default=None,ge=0)
    cron_expression: str|None=None; max_attempts: int=Field(default=3,ge=1,le=100)
    retry_strategy: RetryStrategy=RetryStrategy.exponential; retry_delay_seconds: int=Field(default=30,ge=1,le=86400)
    timeout_seconds: int=Field(default=300,ge=1,le=86400); idempotency_key: str|None=Field(default=None,max_length=200)
    @field_validator("cron_expression")
    @classmethod
    def valid_cron(cls,v):
        if v:
            from croniter import croniter
            if not croniter.is_valid(v): raise ValueError("Invalid cron expression")
        return v
class JobOut(ORM):
    id: uuid.UUID; queue_id: uuid.UUID; name: str; payload: dict[str,Any]; status: JobStatus; priority: int
    scheduled_at: datetime; cron_expression: str|None; next_run_at: datetime|None; max_attempts: int; attempt_count: int
    retry_strategy: RetryStrategy; retry_delay_seconds: int; timeout_seconds: int; claimed_by: uuid.UUID|None
    result: dict[str,Any]|None; last_error: str|None; created_at: datetime; updated_at: datetime
class WorkerRegister(BaseModel):
    project_id: uuid.UUID; name: str=Field(min_length=1,max_length=160); queues: list[str]=Field(default_factory=list); metadata: dict[str,Any]=Field(default_factory=dict)
class WorkerOut(ORM):
    id: uuid.UUID; project_id: uuid.UUID; name: str; status: WorkerStatus; queues: list[str]; last_heartbeat_at: datetime
class Completion(BaseModel):
    success: bool; result: dict[str,Any]|None=None; error: str|None=None
class ExecutionOut(ORM):
    id: uuid.UUID; job_id: uuid.UUID; worker_id: uuid.UUID|None; attempt: int; started_at: datetime; finished_at: datetime|None; status: JobStatus; error: str|None; result: dict[str,Any]|None
class Metrics(BaseModel):
    total_jobs: int; queued: int; running: int; succeeded: int; failed: int; dead: int; active_workers: int; success_rate: float
