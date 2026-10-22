#!/usr/bin/env python3
from __future__ import annotations

import hashlib, json, re, zipfile
from collections import Counter
from pathlib import Path
from docx import Document

ROOT=Path(__file__).resolve().parent; DOCS=ROOT/"documents"; MANIFEST=ROOT/"benchmark_manifest.json"
ABSENT={"D10-C03":["database failover","database migration"],"D12-C03":["third-party oversight finding","third party oversight finding"],"D14-C03":["database migration"]}
LEAK_PATTERNS=[r"\bD\d{2}-C\d{2}\b",r"expected_section_path",r"must_not_target",r"likely_failure_category",r"\bdistractor\b"]
STOP={"the","a","an","and","or","to","of","in","at","is","was","were","for","on","no"}

def hierarchy(doc):
 out=[]; parent=None
 for p in doc.paragraphs:
  if p.style.name=="Heading 1": parent=p.text.strip(); out.append(parent)
  elif p.style.name=="Heading 2" and parent: out.append(parent+" > "+p.text.strip())
 return out

def children(doc,parent):
 out=[]; active=None
 for p in doc.paragraphs:
  if p.style.name=="Heading 1": active=p.text.strip()
  elif p.style.name=="Heading 2" and active==parent: out.append(p.text.strip())
 return out

def section_text(doc,path):
 target=path.split(" > ")[-1]; parent=path.split(" > ")[0] if " > " in path else None; active=None; collect=False; parts=[]
 for p in doc.paragraphs:
  if p.style.name=="Heading 1": active=p.text.strip(); collect=False
  elif p.style.name=="Heading 2": collect=p.text.strip()==target and (parent is None or active==parent)
  elif collect: parts.append(p.text)
 return " ".join(parts).strip()

def tokens(s): return set(re.findall(r"[a-z0-9]+",(s or "").lower()))-STOP
def leaf(path): return re.sub(r"^\d+(?:\.\d+)*\s*","",path.split(" > ")[-1])

def special_checks(cid,doc,heads,errors):
 checks=[]
 siblings={"D04-C02":("Corrective Actions","Long-Term Actions","Verification"),"D13-C02":("Financial Outlook","Decision","Actions")}
 if cid in siblings:
  parent,prior,target=siblings[cid]; order=children(doc,parent); checks.append("relative sibling order")
  if prior not in order or target not in order or order.index(target)!=order.index(prior)+1: errors.append(f"{cid}: {target} is not immediately after {prior} under {parent}")
 ordinals={"D14-C02":("Known Issues","Mobile SDK 4.1 > Known Issues",3)}
 if cid in ordinals:
  name,target,n=ordinals[cid]; occurrences=[h for h in heads if " > " in h and leaf(h)==name]; checks.append(f"ordinal occurrence {n}")
  if len(occurrences)<n or occurrences[n-1]!=target: errors.append(f"{cid}: expected {target} as occurrence {n}; found {occurrences}")
 if cid=="D03-C05":
  beacon=" ".join(section_text(doc,f"Beacon Desk > {name}") for name in ("Security Assessment","Commercial Assessment","Recommendation"))
  checks.append("Beacon sections contain no overall numerical score")
  if re.search(r"overall.{0,30}score|score.{0,30}overall",beacon,re.I): errors.append("D03-C05: Beacon Desk unexpectedly has an overall score")
 if cid=="D11-C04":
  decision=section_text(doc,"Decisions > Decision Log")
  checks.append("decision due date exists without an owner")
  if "March 9" not in decision or re.search(r"\b(owner|owns|owned by)\b",decision,re.I): errors.append("D11-C04: decision due-date/owner assumption no longer holds")
 return checks

def main():
 errors=[]; warnings=[]; data=json.loads(MANIFEST.read_text()); files=sorted(DOCS.glob("*.docx"))
 if len(files)!=14: errors.append(f"Expected 14 DOCX files, found {len(files)}")
 if data.get("case_count")!=len(data.get("cases",[])): errors.append("Manifest case_count mismatch")
 if data.get("corpus_version")!="1.1.0": errors.append("Expected corpus version 1.1.0")
 if len(data["cases"])!=60: errors.append("Expected exactly 60 benchmark cases")
 ids=[c["case_id"] for c in data["cases"]]
 if len(ids)!=len(set(ids)): errors.append("Case IDs are not unique")
 docs_by_id={d["document_id"]:d for d in data["documents"]}; parsed={}; stats=[]
 for path in files:
  try:
   if not zipfile.is_zipfile(path): raise ValueError("not an OOXML zip")
   doc=Document(path); heads=hierarchy(doc); text="\n".join(p.text for p in doc.paragraphs); did=path.name[:3]; sha=hashlib.sha256(path.read_bytes()).hexdigest(); expected=docs_by_id.get(did)
   wc=sum(len(p.text.split()) for p in doc.paragraphs)+sum(len(cell.text.split()) for table in doc.tables for row in table.rows for cell in row.cells)
   parsed[did]=(doc,heads,text)
   if not expected: errors.append(f"{path.name}: missing document manifest entry")
   elif expected["filename"]!=path.name or expected["sha256"]!=sha or expected["fixture_version"]!=data.get("fixture_version"): errors.append(f"{path.name}: filename/hash/version mismatch")
   if not any(p.style.name=="Heading 1" for p in doc.paragraphs) or not any(p.style.name=="Heading 2" for p in doc.paragraphs): errors.append(f"{path.name}: missing real heading hierarchy")
   for pattern in LEAK_PATTERNS:
    if re.search(pattern,text,re.I): errors.append(f"{path.name}: benchmark metadata leak matching {pattern}")
   stats.append({"document_id":did,"filename":path.name,"word_count":wc,"heading_paths":len(heads),"sha256":sha})
  except Exception as exc: errors.append(f"{path.name}: malformed/unreadable DOCX: {exc}")
 audits=[]
 for c in data["cases"]:
  before=len(errors); checks=[]; cid=c["case_id"]
  for req in ("difficulty","expected_behavior","capability_tested","fixture_version","likely_failure_category"):
   if not c.get(req): errors.append(f"{cid}: missing {req}")
  if c["document_id"] not in parsed: errors.append(f"{cid}: document reference does not resolve"); continue
  doc,heads,text=parsed[c["document_id"]]; target=c.get("expected_section_path")
  if c["expected_behavior"]=="unique_target":
   if target not in heads: errors.append(f"{cid}: expected path absent: {target}")
   else:
    checks.append("target path exists")
    if not section_text(doc,target): errors.append(f"{cid}: target section has no content")
    else: checks.append("target content exists")
   if c["case_type"]=="search" and c.get("expected_answer") and target in heads:
    wanted=tokens(c["expected_answer"]); found=tokens(target+" "+section_text(doc,target)); coverage=len(wanted&found)/max(1,len(wanted))
    if coverage<.55: errors.append(f"{cid}: expected answer insufficiently evidenced in target ({coverage:.0%})")
    else: checks.append(f"answer evidence {coverage:.0%}")
  acceptable=c.get("acceptable_section_paths",[])
  for path in acceptable:
   if path not in heads: errors.append(f"{cid}: acceptable path absent: {path}")
   elif not section_text(doc,path): errors.append(f"{cid}: acceptable path has no content: {path}")
  if acceptable: checks.append(f"{len(acceptable)} acceptable paths exist")
  for path in c.get("must_not_target",[]):
   if path not in heads: errors.append(f"{cid}: must_not_target path absent: {path}")
   elif not section_text(doc,path): errors.append(f"{cid}: must_not_target section has no content: {path}")
  if c.get("must_not_target"): checks.append(f"{len(c['must_not_target'])} distractor paths exist")
  if any(x in c["capability_tested"] for x in ("repeated","ordinal")) and target:
   count=sum(1 for h in heads if leaf(h)==leaf(target))
   if count<2: errors.append(f"{cid}: required repeated heading occurs {count} time(s)")
   else: checks.append(f"repeated heading count {count}")
  if c["expected_behavior"]=="should_clarify":
   if target is not None or len(acceptable)<2: errors.append(f"{cid}: SHOULD_CLARIFY requires no unique target and at least two candidates")
   elif len({section_text(doc,p) for p in acceptable})<2: errors.append(f"{cid}: SHOULD_CLARIFY candidates are not substantively distinct")
   else: checks.append("genuine ambiguity: omitted scope with distinct candidates")
  if c["expected_behavior"]=="no_target":
   if target is not None or acceptable: errors.append(f"{cid}: NO_TARGET unexpectedly defines a target")
   for phrase in ABSENT.get(cid,[]):
    if phrase in text.lower(): errors.append(f"{cid}: absent concept unexpectedly present: {phrase}")
   checks.append("requested specific concept absent")
  checks.extend(special_checks(cid,doc,heads,errors)); audits.append({"case_id":cid,"status":"PASS" if len(errors)==before else "FAIL","checks":checks})
 counts=Counter(c["document_id"] for c in data["cases"])
 expected_counts={"D01":4,"D02":5,"D03":5,"D04":4,"D05":5,"D06":3,"D07":5,"D08":4,"D09":4,"D10":4,"D11":4,"D12":5,"D13":4,"D14":4}
 if dict(counts)!=expected_counts: errors.append(f"Unexpected cases per document: {dict(counts)}")
 report={"status":"PASS" if not errors else "FAIL","corpus_version":data.get("corpus_version"),"fixture_version":data.get("fixture_version"),"frozen":data.get("status")=="frozen","documents":stats,"document_count":len(files),"case_count":len(data["cases"]),"cases_per_document":dict(sorted(counts.items())),"case_type_distribution":dict(Counter(c["case_type"] for c in data["cases"])),"difficulty_distribution":dict(Counter(c["difficulty"] for c in data["cases"])),"expected_behavior_distribution":dict(Counter(c["expected_behavior"] for c in data["cases"])),"taxonomy_coverage":dict(sorted(Counter(c["likely_failure_category"] for c in data["cases"]).items())),"case_audits":audits,"errors":errors,"warnings":warnings}
 (ROOT/"validation_report.json").write_text(json.dumps(report,indent=2)+"\n"); print(json.dumps(report,indent=2)); return 1 if errors else 0

if __name__=="__main__": raise SystemExit(main())
