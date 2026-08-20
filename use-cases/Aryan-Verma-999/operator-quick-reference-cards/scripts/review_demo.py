from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from linecard.m1 import write_artifacts, verify

def main():
    result=write_artifacts(); report=verify(result["html"])
    print(json.dumps({"manual_pages":len(result["mapping"]["pages"]),"manual_sha256":result["mapping"]["manual_sha256"],"evidence_records":len(result["evidence"]["records"]),"html_sha256":result["html_sha256"],"verifier":report["status"],"offline":True},indent=2))
    return 0 if report["status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
