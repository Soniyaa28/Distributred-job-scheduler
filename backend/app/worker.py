"""Reference HTTP worker. Replace execute() with application-specific dispatch."""
import asyncio, os, platform
import httpx

API=os.getenv("API_URL","http://api:8000/api/v1")
TOKEN=os.environ["WORKER_TOKEN"]; PROJECT=os.environ["PROJECT_ID"]; QUEUE=os.environ["QUEUE_ID"]
NAME=os.getenv("WORKER_NAME",platform.node())
async def execute(job:dict)->dict:
    # The reference executor intentionally models useful deterministic work.
    # Production consumers can import handlers and route on job["name"].
    await asyncio.sleep(float(job["payload"].get("duration",0)))
    if job["payload"].get("fail"): raise RuntimeError(str(job["payload"].get("message","Requested failure")))
    return {"processed":True,"job_id":job["id"]}
async def run():
    headers={"Authorization":f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(base_url=API,headers=headers,timeout=30) as client:
        r=await client.post("/workers",json={"project_id":PROJECT,"name":NAME,"queues":[QUEUE],"metadata":{"runtime":"python"}}); r.raise_for_status()
        worker=r.json()
        while True:
            await client.post(f"/workers/{worker['id']}/heartbeat")
            r=await client.post(f"/workers/{worker['id']}/claim",params={"queue_id":QUEUE}); r.raise_for_status()
            job=r.json()
            if not job: await asyncio.sleep(2); continue
            try: body={"success":True,"result":await asyncio.wait_for(execute(job),job["timeout_seconds"])}
            except Exception as exc: body={"success":False,"error":f"{type(exc).__name__}: {exc}"}
            r=await client.post(f"/workers/{worker['id']}/jobs/{job['id']}/complete",json=body); r.raise_for_status()
if __name__=="__main__": asyncio.run(run())
