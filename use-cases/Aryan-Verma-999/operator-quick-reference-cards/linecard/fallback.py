"""M1 fallback: SuperDocs stages reviewed content; LineCard owns placement."""
from __future__ import annotations
import re
from .m1 import QUOTES, evidence_pack, skeleton, verify

SIDECAR = {"SAFE-001":"safety_gate", "STEP-001":"procedure[0]", "STEP-002":"procedure[1]", "STEP-003":"procedure[2]", "SPEC-001":"specification", "RESTART-001":"restart"}

def sidecar_manifest(evidence=None):
    pack=evidence or evidence_pack()
    return {"schema":"linecard-sidecar-v1","manual_sha256":pack["manual_sha256"],"blocks":SIDECAR,"evidence_ids":sorted(SIDECAR)}

def verify_staging_content(html: str, evidence=None) -> dict:
    """Verify staged content without treating provider layout/metadata as trusted."""
    evidence=evidence or evidence_pack(); checks=[]
    visible=re.sub(r"<style.*?</style>|<script.*?</script>"," ",html,flags=re.S|re.I); visible=re.sub(r"<[^>]+>"," ",visible)
    checks.append(("EXACT_SPECIFICATION","24 N·m ± 2 N·m" in visible,["SPEC-001"]))
    checks.append(("REQUIRED_SAFETY",QUOTES["SAFE-001"][0] in visible,["SAFE-001"]))
    for eid in ("STEP-001","STEP-002","STEP-003","RESTART-001"): checks.append(("REQUIRED_CONTENT",QUOTES[eid][0] in visible,[eid]))
    checks.append(("CITATION_PAGE_POINTERS","PDF p. 3" in visible and QUOTES["SPEC-001"][0] in visible,["SPEC-001"]))
    nums=set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?",visible)); checks.append(("UNSUPPORTED_NUMERIC_VALUE",nums <= {"1","2","3","4","24","100","001","002","003"},[]))
    checks.append(("HOSTILE_CONTENT_INERT","example.invalid" not in html and "Ignore previous instructions" not in visible,[]))
    return {"status":"PASS" if all(x[1] for x in checks) else "BLOCKED","checks":[{"check_id":a,"passed":b,"evidence_ids":c} for a,b,c in checks]}

def compose_verified_card(staging_html: str, evidence=None) -> tuple[str, dict]:
    evidence=evidence or evidence_pack(); staged=verify_staging_content(staging_html,evidence)
    if staged["status"] != "PASS": raise ValueError("staged authoritative content failed source-lock checks")
    final=skeleton(evidence=evidence); report=verify(final,evidence)
    if report["status"] != "PASS": raise ValueError("deterministic local composition failed final verification")
    return final, {"sidecar":sidecar_manifest(evidence),"staging_verifier":staged,"final_verifier":report}
