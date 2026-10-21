"""Deterministic M1 LineCard pipeline and fail-closed verifier."""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).parents[1]
MANUAL = ROOT / "fixtures/m0-tiny-manual.pdf"
MANUAL_SHA256 = hashlib.sha256(MANUAL.read_bytes()).hexdigest()
PARSER = f"PyMuPDF {fitz.VersionBind}"

QUOTES = {
    "SAFE-001": ("Isolate electrical and pneumatic energy before clearing a jam.", 0, "safety"),
    "STEP-001": ("1. Stop the infeed.", 1, "procedure"),
    "STEP-002": ("2. Verify stored energy is released.", 1, "procedure"),
    "STEP-003": ("3. Remove the obstruction using the approved tool.", 1, "procedure"),
    "SPEC-001": ("Guard fastener torque: 24 N·m ± 2 N·m.", 2, "specification"),
    "RESTART-001": ("Replace the guard and verify the interlock before restart.", 3, "restart"),
}

@dataclass(frozen=True)
class Page:
    pdf_index: int
    display_page: int
    width: float
    height: float
    native_text: str
    text: str
    words: list[dict[str, Any]]
    sha256: str

@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    manual_sha256: str
    page_index: int
    display_page: int
    exact_quote: str
    bbox: list[float]
    quote_sha256: str
    kind: str
    required: bool = True

def page_map(path: Path = MANUAL) -> dict[str, Any]:
    raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    doc = fitz.open(stream=raw, filetype="pdf"); pages = []
    for i, page in enumerate(doc):
        native = page.get_text("text")
        # The synthetic fixture's built-in Helvetica encoding extracts two visible
        # Unicode glyphs as accent-prefixed codes. Retain native_text and expose
        # the deterministic Unicode repair used by the evidence contract.
        text = native.replace("´•", "·").replace("´–", "±")
        words = [{"x0": w[0], "y0": w[1], "x1": w[2], "y1": w[3], "text": w[4], "block": w[5], "line": w[6], "word": w[7]} for w in page.get_text("words")]
        pages.append(asdict(Page(i, i + 1, page.rect.width, page.rect.height, native, text, words, hashlib.sha256(native.encode()).hexdigest())))
    return {"manual_sha256": digest, "parser": PARSER, "schema": "linecard-page-map-v1", "pages": pages}

def evidence_pack(mapping: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping = mapping or page_map(); result = []
    for eid, (quote, index, kind) in QUOTES.items():
        page = mapping["pages"][index]; assert quote in page["text"], f"{eid} missing from cited page"
        spans = [w for w in page["words"] if w["text"] in quote.replace(".", "").split()]
        bbox = [min((w["x0"] for w in spans), default=0), min((w["y0"] for w in spans), default=0), max((w["x1"] for w in spans), default=0), max((w["y1"] for w in spans), default=0)]
        result.append(asdict(Evidence(eid, mapping["manual_sha256"], index, index + 1, quote, bbox, hashlib.sha256(quote.encode()).hexdigest(), kind)))
    return {"manual_sha256": mapping["manual_sha256"], "records": result}

def card_plan(evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    ids = {x["evidence_id"] for x in (evidence or evidence_pack())["records"]}
    return {"identity": {"machine": "LC-100 Synthetic Infeed", "task": "Clear a jam on the infeed"},
      "safety_gate": {"text": QUOTES["SAFE-001"][0], "evidence_ids": ["SAFE-001"]},
      "tools_materials": {"text": "Approved obstruction-removal tool", "evidence_ids": ["STEP-003"]},
      "procedure": [{"text": QUOTES[eid][0], "evidence_ids": [eid]} for eid in ("STEP-001", "STEP-002", "STEP-003")],
      "specification": {"text": QUOTES["SPEC-001"][0], "evidence_ids": ["SPEC-001"]},
      "restart": {"text": QUOTES["RESTART-001"][0], "evidence_ids": ["RESTART-001"]},
      "flow": "START -> energy isolated? no -> STOP; yes -> clear obstruction -> guard replaced and interlock verified? no -> STOP; yes -> COMPLETE",
      "stop": "STOP if energy cannot be isolated, the obstruction cannot be removed with the approved tool, or the interlock fails.",
      "source_index": "Sources: PDF p. 1 SAFE-001; PDF p. 2 STEP-001/002/003; PDF p. 3 SPEC-001; PDF p. 4 RESTART-001.",
      "disclaimer": "Reviewed job aid subordinate to the OEM manual and site safety procedures. Not a safety certification.", "_evidence_ids": sorted(ids)}

def esc(value: Any) -> str: return html.escape(str(value), quote=True)
def pointer(eid: str, evidence: dict[str, Any]) -> str:
    e = next(x for x in evidence["records"] if x["evidence_id"] == eid)
    return f"<span class=\"source-pointer\" data-protected data-evidence-ids=\"{esc(eid)}\">PDF p. {e['display_page']}</span>"

def skeleton(plan: dict[str, Any] | None = None, evidence: dict[str, Any] | None = None) -> str:
    evidence = evidence or evidence_pack(); plan = plan or card_plan(evidence)
    proc = "".join(f"<li data-protected data-step-id=\"{esc(x['evidence_ids'][0])}\">{esc(x['text'])} {pointer(x['evidence_ids'][0], evidence)}</li>" for x in plan["procedure"])
    diagram = '<svg class="flow-diagram" data-flow-evidence-ids="SAFE-001,RESTART-001,STEP-003" role="img" aria-label="Energy isolation and interlock decision flow" viewBox="0 0 600 100"><title>Energy isolation and interlock decision flow</title><rect x="4" y="25" width="150" height="45"/><text x="18" y="52">Isolate energy</text><path d="M155 48 H220" stroke="black"/><polygon points="220,48 210,43 210,53"/><rect x="225" y="25" width="150" height="45"/><text x="240" y="52">Clear obstruction</text><path d="M376 48 H440" stroke="black"/><polygon points="440,48 430,43 430,53"/><rect x="445" y="25" width="150" height="45"/><text x="460" y="52">Verify interlock</text></svg>'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>LineCard</title><style>@page{{size:A4;margin:12mm}}.card-page{{height:273mm;page-break-after:always;box-sizing:border-box}}.card-page:last-child{{page-break-after:auto}}body{{font:11pt sans-serif}}.safety{{border:2px solid #900;padding:10px}}.flow{{border:1px solid #555;padding:8px}}</style></head><body>
<section class="card-page card-page-1"><header data-protected><h1>{esc(plan['identity']['machine'])}</h1><h2>{esc(plan['identity']['task'])}</h2></header>
<section class="safety" data-protected data-safety-id="SAFE-001"><h2>SAFETY GATE</h2><p>{esc(plan['safety_gate']['text'])} {pointer('SAFE-001', evidence)}</p></section>
<section data-compressible><h2>Tools / materials</h2><p>{esc(plan['tools_materials']['text'])} {pointer('STEP-003', evidence)}</p></section>
<section data-protected><h2>Procedure</h2><ol>{proc}</ol></section></section>
<section class="card-page card-page-2"><h2>Decision flow</h2><div class="flow" data-protected>{diagram}</div>
<section data-protected data-spec-id="SPEC-001"><h2>Exact specification</h2><p>{esc(plan['specification']['text'])} {pointer('SPEC-001', evidence)}</p></section>
<section data-protected><h2>Restart / return to service</h2><p data-step-id="RESTART-001">{esc(plan['restart']['text'])} {pointer('RESTART-001', evidence)}</p></section>
<section data-compressible><h2>Stop / escalate</h2><p>{esc(plan['stop'])}</p></section><section data-protected><h2>Source index</h2><p>{esc(plan['source_index'])}</p></section><footer data-compressible>{esc(plan['disclaimer'])}</footer></section></body></html>'''

def _report(checks: list[tuple[str, bool, list[str], str]]) -> dict[str, Any]:
    ids = {"exact specification SPEC-001":"EXACT_SPECIFICATION", "required safety SAFE-001":"REQUIRED_SAFETY", "required STEP-001":"REQUIRED_PROCEDURE_COVERAGE", "required STEP-002":"REQUIRED_PROCEDURE_COVERAGE", "required STEP-003":"REQUIRED_PROCEDURE_COVERAGE", "required RESTART-001":"RESTART_COVERAGE", "protected page containers":"PROTECTED_STRUCTURE", "wrong-page citation":"CITATION_PAGE_POINTERS", "unsupported operational numbers":"UNSUPPORTED_NUMERIC_VALUE", "hostile content inert":"HOSTILE_CONTENT_INERT", "no active source URL/script":"HOSTILE_CONTENT_INERT", "two-page postflight":"TWO_PAGE_HTML_STRUCTURE"}
    return {"status": "PASS" if all(x[1] for x in checks) else "BLOCKED", "checks": [{"check_id": ids.get(a, a.upper().replace(" ", "_")), "check": a, "passed": b, "evidence_ids": c, "expected": "PASS", "observed": "PASS" if b else "BLOCKED", "reason": d} for a,b,c,d in checks]}

def verify(html_text: str, evidence: dict[str, Any] | None = None, pages: int = 2) -> dict[str, Any]:
    evidence = evidence or evidence_pack(); checks=[]
    def add(name, ok, ids, reason): checks.append((name, ok, ids, reason))
    add("exact specification SPEC-001", "24 N·m ± 2 N·m" in html_text, ["SPEC-001"], "exact source string is absent or changed")
    add("required safety SAFE-001", QUOTES["SAFE-001"][0] in html_text, ["SAFE-001"], "required energy-isolation wording is absent or weakened")
    for eid in ("STEP-001","STEP-002","STEP-003","RESTART-001"):
        add(f"required {eid}", QUOTES[eid][0] in html_text and f"PDF p. {QUOTES[eid][1]+1}" in html_text, [eid], "step or its visible source pointer is absent")
    add("protected page containers", html_text.count('class="card-page card-page-') == 2 and "page-break-after:always" in html_text, [], "card is not exactly two explicit protected pages")
    citation = bool(re.search(r'<span class="source-pointer"[^>]*data-evidence-ids="SPEC-001"[^>]*>PDF p\. 3</span>', html_text)) and "display:none" not in html_text.lower()
    add("wrong-page citation", citation, ["SPEC-001"], "visible specification citation is not mapped to SPEC-001 at PDF p. 3")
    add("diagram rendered with evidence", 'class="flow-diagram"' in html_text and 'data-flow-evidence-ids="SAFE-001,RESTART-001,STEP-003"' in html_text and "flowchart TD" not in html_text, ["SAFE-001","RESTART-001","STEP-003"], "flow diagram is missing, unsanitized, or lacks provenance")
    # Ignore generated ordinals/page pointers, but reject operational numbers not in trusted evidence/identity.
    visible = re.sub(r"<style.*?</style>|<script.*?</script>", " ", html_text, flags=re.S|re.I)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = re.sub(r"PDF p\. [1-4]|\b[1-3]\.\s", "", visible)
    nums = set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", visible)); allowed={"100","24","2","001","002","003"}  # evidence IDs are structural labels
    add("unsupported operational numbers", nums <= allowed, [], f"unsupported numeric tokens: {sorted(nums-allowed)}")
    add("hostile content inert", "https://example.invalid" not in html_text and "Ignore previous instructions" not in html_text, [], "hostile source text became active card/control content")
    add("no active source URL/script", not re.search(r"<a[^>]+https?://|<script", html_text, re.I), [], "source-derived capability found")
    add("two-page postflight", pages == 2, [], f"PDF page count is {pages}, expected 2")
    return _report(checks)

def write_artifacts() -> dict[str, Any]:
    mapping=page_map(); evidence=evidence_pack(mapping); plan=card_plan(evidence); html_text=skeleton(plan,evidence)
    out=ROOT/"artifacts/m1"; out.mkdir(parents=True, exist_ok=True)
    (out/"page-map.json").write_text(json.dumps(mapping,indent=2,ensure_ascii=False)+"\n")
    (out/"evidence-pack.json").write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n")
    (out/"card-plan.json").write_text(json.dumps(plan,indent=2,ensure_ascii=False)+"\n")
    (out/"skeleton.html").write_text(html_text)
    return {"mapping":mapping,"evidence":evidence,"plan":plan,"html":html_text,"html_sha256":hashlib.sha256(html_text.encode()).hexdigest()}
