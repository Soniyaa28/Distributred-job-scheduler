import uuid
from datetime import datetime, timedelta, timezone
from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Job, JobExecution, JobStatus, Queue, Worker, WorkerStatus

def utcnow(): return datetime.now(timezone.utc)
def retry_delay(job:Job)->int:
    n=max(job.attempt_count,1)
    if job.retry_strategy.value=="fixed": return job.retry_delay_seconds
    if job.retry_strategy.value=="linear": return job.retry_delay_seconds*n
    return min(job.retry_delay_seconds*(2**(n-1)),86400)

async def claim(db:AsyncSession,worker:Worker,queue_id:uuid.UUID)->Job|None:
    # PostgreSQL SKIP LOCKED provides atomic, non-blocking claims across workers.
    # Serialize claims per queue so the count + claim pair cannot exceed its
    # concurrency limit when many workers poll at the same instant.
    queue=await db.scalar(select(Queue).where(Queue.id==queue_id).with_for_update())
    if not queue or queue.is_paused:
        await db.rollback()
        return None
    running=await db.scalar(select(func.count()).select_from(Job).where(Job.queue_id==queue_id,Job.status==JobStatus.running))
    if (running or 0)>=queue.concurrency_limit:
        await db.rollback()
        return None
    job=await db.scalar(select(Job).where(Job.queue_id==queue_id,Job.status==JobStatus.queued,Job.scheduled_at<=utcnow())
        .order_by(Job.priority.desc(),Job.scheduled_at,Job.created_at).with_for_update(skip_locked=True).limit(1))
    if not job: return None
    job.status=JobStatus.running; job.claimed_by=worker.id; job.claimed_at=utcnow(); job.attempt_count+=1
    db.add(JobExecution(job_id=job.id,worker_id=worker.id,attempt=job.attempt_count))
    await db.commit(); await db.refresh(job); return job

async def complete(db:AsyncSession,job:Job,success:bool,result:dict|None,error:str|None)->Job:
    execution=await db.scalar(select(JobExecution).where(JobExecution.job_id==job.id,JobExecution.attempt==job.attempt_count).with_for_update())
    if job.status!=JobStatus.running: return job
    if success:
        job.status=JobStatus.succeeded; job.result=result
    elif job.attempt_count>=job.max_attempts:
        job.status=JobStatus.dead; job.last_error=error
    else:
        job.status=JobStatus.queued; job.scheduled_at=utcnow()+timedelta(seconds=retry_delay(job)); job.last_error=error
    job.claimed_by=None; job.claimed_at=None
    if execution:
        execution.finished_at=utcnow(); execution.status=JobStatus.succeeded if success else JobStatus.failed
        execution.result=result; execution.error=error
    await db.commit(); await db.refresh(job); return job

async def maintenance(db:AsyncSession,stale_seconds:int)->dict[str,int]:
    now=utcnow(); stale=now-timedelta(seconds=stale_seconds)
    workers=(await db.scalars(select(Worker).where(Worker.last_heartbeat_at<stale,Worker.status==WorkerStatus.online))).all()
    for w in workers: w.status=WorkerStatus.offline
    orphaned=(await db.scalars(select(Job).where(Job.status==JobStatus.running,Job.claimed_at<stale).with_for_update(skip_locked=True))).all()
    for j in orphaned:
        j.claimed_by=None; j.claimed_at=None; j.status=JobStatus.dead if j.attempt_count>=j.max_attempts else JobStatus.queued
        j.last_error="Worker heartbeat expired"
    cron_jobs=(await db.scalars(select(Job).where(Job.cron_expression.is_not(None),Job.next_run_at<=now).with_for_update(skip_locked=True))).all()
    for template in cron_jobs:
        run_at=template.next_run_at or now
        db.add(Job(queue_id=template.queue_id,name=template.name,payload=template.payload,priority=template.priority,
                   scheduled_at=run_at,max_attempts=template.max_attempts,retry_strategy=template.retry_strategy,
                   retry_delay_seconds=template.retry_delay_seconds,timeout_seconds=template.timeout_seconds,parent_job_id=template.id))
        template.next_run_at=croniter(template.cron_expression,now).get_next(datetime)
    await db.commit()
    return {"offline_workers":len(workers),"recovered_jobs":len(orphaned),"cron_runs":len(cron_jobs)}
