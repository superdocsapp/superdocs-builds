from __future__ import annotations

import argparse, json, mimetypes, os, re, time, uuid, zipfile
from dataclasses import asdict, dataclass
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def load_local_env() -> None:
    path = Path(".env")
    if path.is_file():
        for line in path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key and not key.lstrip().startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())
load_local_env()

class TaskStatus(StrEnum): PENDING="PENDING"; IN_PROGRESS="IN_PROGRESS"; COMPLETED="COMPLETED"; FAILED="FAILED"; NOT_ATTEMPTED="NOT_ATTEMPTED"
class RunStatus(StrEnum): COMPLETED="COMPLETED"; PARTIALLY_COMPLETED="PARTIALLY_COMPLETED"; FAILED="FAILED"; BUDGET_EXHAUSTED="BUDGET_EXHAUSTED"; DEADLINE_EXCEEDED="DEADLINE_EXCEEDED"
@dataclass
class Task: id:str; description:str; status:TaskStatus=TaskStatus.PENDING; error:str|None=None

class TextOnly(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self,data): self.parts.append(data)

def plain_text(value:str)->str:
    parser=TextOnly(); parser.feed(value); return " ".join("".join(parser.parts).split())

def clipped(value:str,limit:int=280)->str:
    return value if len(value)<=limit else value[:limit-1]+"…"

def plan(request:str)->list[Task]:
    pieces=[re.sub(r"^\d+[.)]\s*","",x.strip()) for x in re.split(r";|\n",request) if x.strip()]
    if not pieces: raise ValueError("Request needs at least one task")
    return [Task(f"T{i}",text) for i,text in enumerate(pieces[:20],1)]

def resource_context(paths:list[str]|None)->str:
    """Read small local references; their text is included with every requested edit."""
    references=[]
    for raw_path in paths or []:
        path=Path(raw_path)
        if not path.is_file(): raise FileNotFoundError(path)
        if path.suffix.lower()==".docx":
            with zipfile.ZipFile(path) as document:
                root=ElementTree.fromstring(document.read("word/document.xml"))
                text=" ".join(node.text or "" for node in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
        elif path.suffix.lower() in {".md",".txt"}: text=path.read_text(errors="replace")
        else: raise ValueError(f"Unsupported resource {path.name}; use .docx, .md, or .txt")
        references.append(f"Reference: {path.name}\n{text[:6000]}")
    return "\n\n".join(references)

def show_changes(task:Task,changes:list[dict],auto:bool)->bool:
    print(f"\nReview {task.id} · {task.description}")
    print("─"*72)
    if not changes: print("SuperDocs did not return itemized diffs. Review the requested task before deciding.")
    for number,change in enumerate(changes,1):
        print(f"{number}. {change.get('operation','edit').capitalize()} in document section")
        old,new=plain_text(change.get("old_html","")),plain_text(change.get("new_html",""))
        if old: print(f"   − {clipped(old)}")
        if new: print(f"   + {clipped(new)}")
        if change.get("ai_explanation"): print(f"   Why: {clipped(change['ai_explanation'])}")
    print("─"*72)
    if auto:
        print("Auto-approved because --auto-approve-demo was supplied.")
        return True
    return input(f"Apply {len(changes)} proposed change(s)? [y/N] ").strip().lower()=="y"

def show_run_result(result:dict)->None:
    print(f"\nRun {result['status']} · {result['operations_used']}/{result['operations_allowed']} operations used")
    if result["completed"]: print("Completed: "+", ".join(result["completed"]))
    if result["failed"]: print("Failed/rejected: "+", ".join(task["id"] for task in result["failed"]))
    unattempted=[task["id"] for task in result["tasks"] if task["status"]==TaskStatus.NOT_ATTEMPTED]
    if unattempted: print("Not attempted: "+", ".join(unattempted))
    if result.get("stop_reason"): print("Stopped: "+result["stop_reason"])
    if result.get("export_path"): print("Export: "+result["export_path"])
    if result.get("export_error"): print("Export failed: "+result["export_error"])

class SuperDocs:
    def __init__(self,key:str,base:str=os.getenv("SUPERDOCS_BASE_URL","https://api.superdocs.app")):
        if not key: raise ValueError("SUPERDOCS_API_KEY is required")
        self.key,self.base=key,base.rstrip("/")
    def request(self,path:str,payload:dict|None=None,body:bytes|None=None,ctype="application/json"):
        headers={"Authorization":f"Bearer {self.key}","Accept":"application/json"}
        body=json.dumps(payload or {}).encode() if body is None else body
        if ctype: headers["Content-Type"]=ctype
        try:
            with urlopen(Request(self.base+path,data=body,headers=headers,method="POST"),timeout=60) as r:
                raw=r.read(); return json.loads(raw) if r.headers.get_content_type()=="application/json" else raw
        except HTTPError as e: raise RuntimeError(f"SuperDocs HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        except URLError as e: raise RuntimeError(f"SuperDocs network error: {e.reason}") from e
    def upload(self,file_path:str,session_id:str)->dict:
        path=Path(file_path); boundary="----run"+uuid.uuid4().hex
        if not path.is_file(): raise FileNotFoundError(path)
        mime=mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body=b"\r\n".join([f"--{boundary}".encode(),b'Content-Disposition: form-data; name="session_id"',b"",session_id.encode(),f"--{boundary}".encode(),f'Content-Disposition: form-data; name="file"; filename="{path.name}"'.encode(),f"Content-Type: {mime}".encode(),b"",path.read_bytes(),f"--{boundary}--".encode(),b""])
        return self.request("/v1/documents/upload?index=true",body=body,ctype=f"multipart/form-data; boundary={boundary}")
    def edit(self,session:str,instruction:str)->dict: return self.request("/v1/chat/async",{"session_id":session,"message":instruction,"approval_mode":"ask_every_time","response_mode":"compact"})
    def job(self,job_id:str)->dict:
        try:
            with urlopen(Request(f"{self.base}/v1/jobs/{job_id}",headers={"Authorization":f"Bearer {self.key}"}),timeout=60) as r:return json.loads(r.read())
        except HTTPError as e: raise RuntimeError(f"SuperDocs HTTP {e.code}") from e
    def approve(self,session:str,job_id:str,changes:list[dict])->dict:return self.request(f"/v1/chat/{session}/approve",{"job_id":job_id,"approved":True,"changes":changes})
    def wait(self,job_id:str,max_polls:int=60)->dict:
        for _ in range(max_polls):
            state=self.job(job_id)
            if state.get("status") not in {"pending","in_progress"}: return state
            time.sleep(1)
        raise RuntimeError("SuperDocs job did not reach a terminal state before polling limit")
    def export(self,session:str,path:str)->str:
        result=self.request("/v1/documents/export",{"session_id":session,"format":"docx"})
        if isinstance(result,dict):
            url=result.get("download_url") or result.get("url")
            if not url: raise RuntimeError("Export returned no artifact")
            with urlopen(url,timeout=60) as r: result=r.read()
        target=Path(path); target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(result)
        if not target.stat().st_size: raise RuntimeError("Export was empty")
        return str(target)

def run(client, file_path:str, request:str, max_operations:int, deadline:float|None, auto:bool, output:str, clock=time.monotonic, resources:list[str]|None=None)->dict:
    if max_operations<1: raise ValueError("max_operations must be at least 1")
    tasks,started,used,stop=plan(request),clock(),0,None; session="run-"+uuid.uuid4().hex; context=resource_context(resources)
    client.upload(file_path,session)
    for task in tasks:
        if used>=max_operations: stop="OPERATION_BUDGET_EXHAUSTED"; break
        if deadline is not None and clock()-started>=deadline: stop="DEADLINE_EXCEEDED"; break
        task.status=TaskStatus.IN_PROGRESS
        try:
            instruction=task.description+(f"\n\nUse these reference resources when relevant:\n{context}" if context else "")
            job=client.edit(session,instruction); used+=1; state=client.wait(job["job_id"])
            if state.get("status")=="awaiting_approval":
                changes=(state.get("metadata") or {}).get("pending_changes") or state.get("pending_changes") or []
                approved=show_changes(task,changes,auto)
                if not approved: task.status,task.error,stop=TaskStatus.FAILED,"Approval rejected","APPROVAL_REJECTED"; break
                client.approve(session,job["job_id"],[{"change_id":c["change_id"],"approved":True} for c in changes]); state=client.wait(job["job_id"])
            if state.get("status")=="completed": task.status=TaskStatus.COMPLETED
            else: task.status,task.error=TaskStatus.FAILED,f"Job ended as {state.get('status','unknown')}"
        except Exception as e: task.status,task.error=TaskStatus.FAILED,str(e)
    if stop:
        for task in tasks:
            if task.status==TaskStatus.PENDING: task.status=TaskStatus.NOT_ATTEMPTED
    completed=sum(x.status==TaskStatus.COMPLETED for x in tasks)
    status=RunStatus.BUDGET_EXHAUSTED if stop=="OPERATION_BUDGET_EXHAUSTED" else RunStatus.DEADLINE_EXCEEDED if stop=="DEADLINE_EXCEEDED" else RunStatus.COMPLETED if completed==len(tasks) else RunStatus.PARTIALLY_COMPLETED if completed else RunStatus.FAILED
    result={"status":status,"stop_reason":stop,"operations_used":used,"operations_allowed":max_operations,"resources":[Path(path).name for path in resources or []],"elapsed_seconds":round(clock()-started,3),"completed":[x.id for x in tasks if x.status==TaskStatus.COMPLETED],"failed":[asdict(x) for x in tasks if x.status==TaskStatus.FAILED],"not_completed":[x.id for x in tasks if x.status!=TaskStatus.COMPLETED],"tasks":[asdict(x) for x in tasks]}
    try: result["export_path"]=client.export(session,output)
    except Exception as e: result["export_error"]=str(e)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser(description="Bounded, human-approved SuperDocs DOCX editor")
    p.add_argument("--file",help="DOCX to edit");p.add_argument("--request",help="Semicolon or newline separated edits");p.add_argument("--resource",action="append",help="Optional .docx, .md, or .txt reference; repeatable")
    p.add_argument("--max-operations",type=int,help="Maximum permitted edits");p.add_argument("--deadline-seconds",type=float);p.add_argument("--auto-approve-demo",action="store_true");p.add_argument("--output",default="output/result.docx");a=p.parse_args()
    file_path=a.file or input("DOCX to edit: ").strip(); request=a.request or input("Editing request: ").strip(); max_operations=a.max_operations if a.max_operations is not None else int(input("Maximum operations: "))
    show_run_result(run(SuperDocs(os.getenv("SUPERDOCS_API_KEY","")),file_path,request,max_operations,a.deadline_seconds,a.auto_approve_demo,a.output,resources=a.resource))
