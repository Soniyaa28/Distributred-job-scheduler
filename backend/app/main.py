import asyncio, uuid
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
from app.api.routes import router
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.services.jobs import maintenance

configure_logging(); log=structlog.get_logger()
async def scheduler_loop():
    while True:
        try:
            async with SessionLocal() as db:
                result=await maintenance(db,settings.worker_stale_seconds)
                if any(result.values()): await log.ainfo("scheduler.maintenance",**result)
        except Exception: await log.aexception("scheduler.error")
        await asyncio.sleep(settings.scheduler_interval_seconds)
@asynccontextmanager
async def lifespan(app:FastAPI):
    task=asyncio.create_task(scheduler_loop())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError): await task
app=FastAPI(title=settings.app_name,version="1.0.0",lifespan=lifespan,
            description="Production distributed job scheduling and queue management API")
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origin_list,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
@app.middleware("http")
async def request_context(request:Request,call_next):
    request_id=request.headers.get("x-request-id",str(uuid.uuid4())); structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response=await call_next(request); response.headers["x-request-id"]=request_id; return response
    finally: structlog.contextvars.clear_contextvars()
@app.get("/health")
async def health(): return {"status":"ok","service":settings.app_name}
app.include_router(router)
