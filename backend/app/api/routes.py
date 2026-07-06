import asyncio, uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import current_user, owned_job, owned_project, owned_queue
from app.core.database import SessionLocal, get_db
from app.core.security import create_token, hash_password, verify_password
from app.models import Job, JobExecution, JobStatus, Project, Queue, User, Worker, WorkerStatus
from app.schemas import *
from app.services.jobs import claim, complete, maintenance

router=APIRouter(prefix="/api/v1")

@router.post("/auth/register",response_model=UserOut,status_code=201)
async def register(body:Register,db:AsyncSession=Depends(get_db)):
    if await db.scalar(select(User).where(User.email==body.email.lower())): raise HTTPException(409,"Email already registered")
    user=User(email=body.email.lower(),password_hash=hash_password(body.password),full_name=body.full_name)
    db.add(user); await db.commit(); await db.refresh(user); return user
@router.post("/auth/login",response_model=Token)
async def login(body:Login,db:AsyncSession=Depends(get_db)):
    user=await db.scalar(select(User).where(User.email==body.email.lower()))
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,"Invalid credentials")
    return Token(access_token=create_token(str(user.id)))
@router.get("/auth/me",response_model=UserOut)
async def me(user:User=Depends(current_user)): return user

@router.post("/projects",response_model=ProjectOut,status_code=201)
async def create_project(body:ProjectCreate,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    p=Project(owner_id=user.id,**body.model_dump()); db.add(p)
    try: await db.commit()
    except IntegrityError: await db.rollback(); raise HTTPException(409,"Project name already exists")
    await db.refresh(p); return p
@router.get("/projects",response_model=list[ProjectOut])
async def projects(user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    return (await db.scalars(select(Project).where(Project.owner_id==user.id).order_by(Project.created_at.desc()))).all()
@router.delete("/projects/{project_id}",status_code=204)
async def delete_project(project_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    p=await owned_project(db,user,project_id); await db.delete(p); await db.commit()

@router.post("/queues",response_model=QueueOut,status_code=201)
async def create_queue(body:QueueCreate,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_project(db,user,body.project_id); q=Queue(**body.model_dump()); db.add(q)
    try: await db.commit()
    except IntegrityError: await db.rollback(); raise HTTPException(409,"Queue name already exists")
    await db.refresh(q); return q
@router.get("/queues",response_model=list[QueueOut])
async def queues(project_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_project(db,user,project_id)
    return (await db.scalars(select(Queue).where(Queue.project_id==project_id).order_by(Queue.name))).all()
@router.patch("/queues/{queue_id}",response_model=QueueOut)
async def patch_queue(queue_id:uuid.UUID,body:QueuePatch,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    q=await owned_queue(db,user,queue_id)
    for k,v in body.model_dump(exclude_unset=True).items(): setattr(q,k,v)
    await db.commit(); await db.refresh(q); return q

@router.post("/jobs",response_model=JobOut,status_code=201)
async def create_job(body:JobCreate,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_queue(db,user,body.queue_id); data=body.model_dump(exclude={"delay_seconds"})
    now=datetime.now(timezone.utc); data["scheduled_at"]=body.scheduled_at or (now+timedelta(seconds=body.delay_seconds or 0))
    if body.cron_expression: data["next_run_at"]=data["scheduled_at"]; data["status"]=JobStatus.scheduled
    job=Job(**data); db.add(job)
    try: await db.commit()
    except IntegrityError: await db.rollback(); raise HTTPException(409,"Idempotency key already used")
    await db.refresh(job); return job
@router.get("/jobs",response_model=list[JobOut])
async def jobs(queue_id:uuid.UUID,status_:JobStatus|None=Query(None,alias="status"),limit:int=Query(100,le=500),offset:int=0,
               user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_queue(db,user,queue_id); stmt=select(Job).where(Job.queue_id==queue_id)
    if status_: stmt=stmt.where(Job.status==status_)
    return (await db.scalars(stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset))).all()
@router.get("/jobs/{job_id}",response_model=JobOut)
async def get_job(job_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)): return await owned_job(db,user,job_id)
@router.post("/jobs/{job_id}/cancel",response_model=JobOut)
async def cancel(job_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    j=await owned_job(db,user,job_id)
    if j.status not in (JobStatus.queued,JobStatus.scheduled): raise HTTPException(409,"Only pending jobs can be cancelled")
    j.status=JobStatus.cancelled; await db.commit(); await db.refresh(j); return j
@router.post("/jobs/{job_id}/requeue",response_model=JobOut)
async def requeue(job_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    j=await owned_job(db,user,job_id)
    if j.status not in (JobStatus.dead,JobStatus.failed): raise HTTPException(409,"Only failed/dead jobs can be requeued")
    j.status=JobStatus.queued; j.attempt_count=0; j.scheduled_at=datetime.now(timezone.utc); j.last_error=None
    await db.commit(); await db.refresh(j); return j
@router.get("/jobs/{job_id}/executions",response_model=list[ExecutionOut])
async def executions(job_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_job(db,user,job_id)
    return (await db.scalars(select(JobExecution).where(JobExecution.job_id==job_id).order_by(JobExecution.attempt.desc()))).all()

@router.post("/workers",response_model=WorkerOut,status_code=201)
async def register_worker(body:WorkerRegister,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_project(db,user,body.project_id)
    w=await db.scalar(select(Worker).where(Worker.project_id==body.project_id,Worker.name==body.name))
    if w: w.status=WorkerStatus.online; w.last_heartbeat_at=datetime.now(timezone.utc); w.queues=body.queues; w.metadata_=body.metadata
    else: w=Worker(project_id=body.project_id,name=body.name,queues=body.queues,metadata_=body.metadata); db.add(w)
    await db.commit(); await db.refresh(w); return w
@router.get("/workers",response_model=list[WorkerOut])
async def workers(project_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_project(db,user,project_id); return (await db.scalars(select(Worker).where(Worker.project_id==project_id))).all()
@router.post("/workers/{worker_id}/heartbeat",response_model=WorkerOut)
async def heartbeat(worker_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    w=await db.scalar(select(Worker).join(Project).where(Worker.id==worker_id,Project.owner_id==user.id))
    if not w: raise HTTPException(404,"Worker not found")
    w.last_heartbeat_at=datetime.now(timezone.utc); w.status=WorkerStatus.online; await db.commit(); await db.refresh(w); return w
@router.post("/workers/{worker_id}/claim",response_model=JobOut|None)
async def claim_job(worker_id:uuid.UUID,queue_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    q=await owned_queue(db,user,queue_id); w=await db.get(Worker,worker_id)
    if not w or w.project_id!=q.project_id: raise HTTPException(404,"Worker not found")
    return await claim(db,w,queue_id)
@router.post("/workers/{worker_id}/jobs/{job_id}/complete",response_model=JobOut)
async def complete_job(worker_id:uuid.UUID,job_id:uuid.UUID,body:Completion,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    j=await owned_job(db,user,job_id)
    if j.claimed_by!=worker_id: raise HTTPException(409,"Job is not claimed by this worker")
    return await complete(db,j,body.success,body.result,body.error)

@router.get("/metrics",response_model=Metrics)
async def metrics(project_id:uuid.UUID,user:User=Depends(current_user),db:AsyncSession=Depends(get_db)):
    await owned_project(db,user,project_id)
    rows=(await db.execute(select(Job.status,func.count(Job.id)).join(Queue).where(Queue.project_id==project_id).group_by(Job.status))).all()
    c={s.value:n for s,n in rows}; total=sum(c.values()); success=c.get("succeeded",0); terminal=success+c.get("dead",0)+c.get("failed",0)
    active=await db.scalar(select(func.count()).select_from(Worker).where(Worker.project_id==project_id,Worker.status==WorkerStatus.online))
    return Metrics(total_jobs=total,queued=c.get("queued",0),running=c.get("running",0),succeeded=success,failed=c.get("failed",0),
                   dead=c.get("dead",0),active_workers=active or 0,success_rate=round(success/terminal*100,2) if terminal else 0)
