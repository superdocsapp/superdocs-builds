"""Non-billable exact-HTML PDF export probe. Never calls chat."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import verify, write_artifacts
from linecard.superdocs_client import SuperDocsClient

ROOT=Path(__file__).parents[1]
def postflight(pdf):
    import fitz
    doc=fitz.open(stream=pdf,filetype="pdf"); text="\n".join(p.get_text() for p in doc)
    return {"opens":True,"pages":len(doc),"exact_value":"24 N·m ± 2 N·m" in text,"safety":"Isolate electrical and pneumatic energy before clearing a jam." in text,"procedures":all(x in text for x in ("Stop the infeed.","Verify stored energy is released.","Remove the obstruction using the approved tool.")),"restart":"Replace the guard and verify the interlock before restart" in text,"citation":"PDF p. 3" in text}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--dry-run",action="store_true"); args=ap.parse_args(); result=write_artifacts(); report=verify(result["html"])
    if report["status"] != "PASS": print(json.dumps({"chat_calls":0,"export_attempted":False,"verifier":report},indent=2)); return 1
    if args.dry_run: print(json.dumps({"mode":"dry-run","chat_calls":0,"export_attempted":False,"verifier":report,"html_sha256":result["html_sha256"]},indent=2)); return 0
    if os.getenv("RUN_LIVE_SUPERDOCS") != "1": print("live export probe requires RUN_LIVE_SUPERDOCS=1",file=sys.stderr); return 2
    client=SuperDocsClient(); response=client.export_pdf_html(result["html"]); pdf=response.content; pf=postflight(pdf); out=ROOT/"artifacts/m1"; out.mkdir(parents=True,exist_ok=True); (out/"linecard-m1-export-probe.pdf").write_bytes(pdf)
    record={"chat_calls":0,"export_attempted":True,"export_status":response.status_code,"warning_headers":{k:v for k,v in response.headers.items() if "warning" in k.lower()},"html_sha256":result["html_sha256"],"pdf_sha256":hashlib.sha256(pdf).hexdigest(),"pdf_bytes":len(pdf),"postflight":pf}; print(json.dumps(record,indent=2)); return 0 if pf["opens"] and pf["pages"]==2 and all(pf[k] for k in ("exact_value","safety","procedures","restart","citation")) else 1
if __name__=="__main__": raise SystemExit(main())
