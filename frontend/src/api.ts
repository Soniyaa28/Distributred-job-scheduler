const BASE=import.meta.env.VITE_API_URL||"http://localhost:8000/api/v1";
export const token=()=>localStorage.getItem("token");
export async function api<T>(path:string,init:RequestInit={}):Promise<T>{
 const r=await fetch(BASE+path,{...init,headers:{"Content-Type":"application/json",...(token()?{Authorization:`Bearer ${token()}`}:{ }),...init.headers}});
 if(!r.ok) throw new Error((await r.json().catch(()=>({detail:r.statusText}))).detail);
 return r.status===204?undefined as T:r.json()
}
export type Project={id:string;name:string;description?:string};
export type Queue={id:string;project_id:string;name:string;concurrency_limit:number;is_paused:boolean};
export type Job={id:string;name:string;status:string;priority:number;attempt_count:number;max_attempts:number;scheduled_at:string;created_at:string};
export type Metrics={total_jobs:number;queued:number;running:number;succeeded:number;failed:number;dead:number;active_workers:number;success_rate:number};
