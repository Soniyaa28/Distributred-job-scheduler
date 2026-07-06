import uuid
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import decode_token
from app.models import User, Project, Queue, Job

bearer=HTTPBearer()
async def current_user(credentials: HTTPAuthorizationCredentials=Depends(bearer), db: AsyncSession=Depends(get_db))->User:
    user=await db.get(User, uuid.UUID(decode_token(credentials.credentials)))
    if not user or not user.is_active: raise HTTPException(401,"Inactive or missing user")
    return user
async def owned_project(db:AsyncSession,user:User,project_id:uuid.UUID)->Project:
    p=await db.scalar(select(Project).where(Project.id==project_id,Project.owner_id==user.id))
    if not p: raise HTTPException(404,"Project not found")
    return p
async def owned_queue(db:AsyncSession,user:User,queue_id:uuid.UUID)->Queue:
    q=await db.scalar(select(Queue).join(Project).where(Queue.id==queue_id,Project.owner_id==user.id))
    if not q: raise HTTPException(404,"Queue not found")
    return q
async def owned_job(db:AsyncSession,user:User,job_id:uuid.UUID)->Job:
    j=await db.scalar(select(Job).join(Queue).join(Project).where(Job.id==job_id,Project.owner_id==user.id))
    if not j: raise HTTPException(404,"Job not found")
    return j
