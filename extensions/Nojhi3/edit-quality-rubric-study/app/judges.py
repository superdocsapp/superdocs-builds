"""Judges: the automated LLM judge and the human judge's score storage.

Automated judging was first attempted with SuperDocs' own chat model (the
"AutoJudge" class below). Finding from pilot runs: SuperDocs chat is an
editing assistant; when asked to score a document it often replies with a
short acknowledgment ("Done.", "I'll score the edit now.") instead of JSON,
and with approval_mode=ask_every_time it only acknowledges. A JSON scoring
turn therefore uses a general-purpose LLM (Gemini via an OpenAI-compatible
endpoint, default) — recorded in its own token ledger — while the SuperDocs
chat judge remains available for comparison via JUDGE_PROVIDER=superdocs.

Blindness: the judge sees the instruction, source text, and edited text —
never the human's scores.
"""

import json
import time
from typing import Optional

import requests

from . import config
from .budget import BudgetGuard, BudgetExceeded
from .rubric import build_score_sheet, load_rubric, valid_score
from .superdocs_client import SuperDocsClient, SuperDocsError, extract_json_from_text

DIMENSIONS = [
    ("faithfulness", "Faithfulness to instruction"),
    ("fact_accuracy", "Fact accuracy"),
    ("content_preservation", "Content preservation"),
    ("structural_integrity", "Structural integrity"),
    ("formatting_fidelity", "Formatting fidelity"),
    ("language_quality", "Language quality"),
]


def _clip(text: str, limit: int = 4000) -> str:
    """Keep head + tail of long material so prompts stay compact.

    The marker is explicitly framed as a harness note so a judge cannot
    mistake it for document content (a pilot artifact: the judge once scored
    the marker itself)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.6)]
    tail = text[-int(limit * 0.4):]
    return f"{head}\n[HARNESS NOTE: content omitted from judge input for length]\n{tail}"


def build_judge_prompt(case: dict, source_text: str, after_text: str, rubric: dict) -> str:
    anchor_lines = []
    for dim in rubric["dimensions"]:
        a = dim["anchors"]
        anchor_lines.append(
            f"- {dim['id']}: {a['1'][:40]} | {a['2'][:40]} | {a['3'][:40]} | {a['4'][:40]}"
        )
    return (
        "You are a document-edit quality judge. Score ONE edit.\n"
        f"INSTRUCTION: {case['instruction']}\n"
        "RUBRIC (1=Fail,2=Poor,3=Good,4=Excellent):\n"
        + "\n".join(anchor_lines)
        + "\nScore every dimension 1-4 and give a short evidence quote per dimension. "
        "If a dimension cannot be verified from the text (e.g. visual formatting), "
        "score honestly and say so in evidence. A line starting with '[HARNESS NOTE' "
        "means the evaluation harness omitted part of the document for length; "
        "ignore the note itself and judge only the content you can see.\n"
        "Respond with JSON ONLY:\n"
        '{"scores": {"faithfulness":4,"fact_accuracy":4,"content_preservation":4,'
        '"structural_integrity":4,"formatting_fidelity":4,"language_quality":4},'
        '"evidence": {"faithfulness":"...","fact_accuracy":"...","content_preservation":"...",'
        '"structural_integrity":"...","formatting_fidelity":"...","language_quality":"..."}}\n'
        f"SOURCE:\n{_clip(source_text)}\nEDITED:\n{_clip(after_text)}"
    )


def _strip_html(text: str) -> str:
    import html as html_mod
    import re as re_mod

    text = re_mod.sub(r"<[^>]+>", " ", text)
    return html_mod.unescape(re_mod.sub(r"\s+", " ", text)).strip()


def _after_text(case_id: str) -> Optional[str]:
    md_path = config.EDITS_DIR / case_id / "after.md"
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    html_path = config.EDITS_DIR / case_id / "after.html"
    if html_path.exists():
        return _strip_html(html_path.read_text(encoding="utf-8"))
    job_path = config.EDITS_DIR / case_id / "job_final.json"
    if not job_path.exists():
        return None
    job = json.loads(job_path.read_text(encoding="utf-8"))
    changes = (job.get("result") or {}).get("document_changes") or {}
    updated = changes.get("updated_html")
    return _strip_html(updated) if updated else None


def _source_text(case_id: str) -> Optional[str]:
    before_md = config.EDITS_DIR / case_id / "before.md"
    if before_md.exists():
        return before_md.read_text(encoding="utf-8")
    before_html = config.EDITS_DIR / case_id / "before.html"
    if before_html.exists():
        return _strip_html(before_html.read_text(encoding="utf-8"))
    upload_path = config.EDITS_DIR / case_id / "upload.json"
    if not upload_path.exists():
        return None
    upload = json.loads(upload_path.read_text(encoding="utf-8"))
    for key in ("html", "document_html", "converted_html"):
        if upload.get(key):
            return _strip_html(upload[key])
    return None


def _material(case_id: str) -> tuple[Optional[str], Optional[str]]:
    return _source_text(case_id), _after_text(case_id)


def _save_sheet(sheet: dict, rater_dir) -> None:
    path = rater_dir / f"{sheet['case_id']}.json"
    path.write_text(json.dumps(sheet, indent=2), encoding="utf-8")


class GeminiJudge:
    """General-purpose LLM judge via an OpenAI-compatible endpoint.

    Each call is recorded in data/ledger_gemini.jsonl (prompt/completion
    tokens) — separate from SuperDocs operations, which only the edit
    pipeline consumes.
    """

    def __init__(self):
        self.rubric = load_rubric()
        if not config.GEMINI_API_KEY:
            raise RuntimeError("JUDGE_PROVIDER=gemini requires GEMINI_API_KEY in .env")

    def judge_case(self, case: dict) -> dict:
        case_id = case["case_id"]
        source, after = _material(case_id)
        if not after:
            return {"case_id": case_id, "status": "failed",
                    "error": f"no edited text for {case_id} (did the edit pipeline run?)"}
        prompt = build_judge_prompt(case, source or "(source not available)", after, self.rubric)
        out = {"case_id": case_id, "rater": "auto", "provider": "gemini",
               "model": config.GEMINI_MODEL, "status": "running"}

        try:
            resp = requests.post(
                f"{config.GEMINI_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.GEMINI_API_KEY}"},
                json={
                    "model": config.GEMINI_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                timeout=120,
            )
        except requests.exceptions.RequestException as exc:
            out.update({"status": "failed", "error": f"gemini request failed: {exc}"})
            return out
        if resp.status_code >= 400:
            out.update({"status": "failed", "error": f"gemini {resp.status_code}: {resp.text[:400]}"})
            return out
        data = resp.json()
        usage = data.get("usage") or {}
        self._record_usage(usage, case_id)
        out["usage"] = usage

        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        out["response_preview"] = content[:400]
        payload = extract_json_from_text(content)
        if not payload:
            out.update({"status": "failed", "error": "no parseable JSON in judge response",
                        "response": content[:2000]})
            return out

        scores = payload.get("scores") or {}
        evidence = payload.get("evidence") or {}
        invalid = [d for d, s in scores.items() if not valid_score(s)]
        if invalid:
            out.update({"status": "failed", "error": f"invalid scores for {invalid}", "payload": payload})
            return out

        sheet = {
            "case_id": case_id,
            "rater": "auto",
            "provider": "gemini",
            "model": config.GEMINI_MODEL,
            "scores": {d: scores[d] for d, _ in DIMENSIONS},
            "evidence": {d: (evidence.get(d) or "") for d, _ in DIMENSIONS},
            "difficulty": case["difficulty"],
            "instruction": case["instruction"],
        }
        _save_sheet(sheet, config.AUTO_DIR)
        out.update({"status": "completed", "scores": sheet["scores"]})
        return out

    def _record_usage(self, usage: dict, case_id: str) -> None:
        entry = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "case_id": case_id,
            "model": config.GEMINI_MODEL,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
        with config.GEMINI_LEDGER_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def judge_all(self, case_ids: Optional[list[str]] = None) -> dict:
        from .pipeline import load_cases

        summary = {"results": [], "failed": []}
        for case in load_cases():
            if case_ids and case["case_id"] not in case_ids:
                continue
            res = self.judge_case(case)
            summary["results"].append(res)
            if res["status"] != "completed":
                summary["failed"].append(res)
        return summary


class AutoJudge:
    """SuperDocs-chat judge. Kept for comparison; pilot runs showed it often
    answers conversationally instead of scoring (see README finding)."""

    def __init__(self, client: SuperDocsClient = None, max_attempts: int = 3):
        self.client = client or SuperDocsClient()
        self.rubric = load_rubric()
        self.max_attempts = max_attempts

    def judge_case(self, case: dict) -> dict:
        case_id = case["case_id"]
        source, after = _material(case_id)
        if not after:
            return {"case_id": case_id, "status": "failed",
                    "error": f"no edited text for {case_id} (did the edit pipeline run?)"}
        session_id = f"eqr_j_{case_id}_{int(time.time())}"
        out = {"case_id": case_id, "rater": "auto", "provider": "superdocs",
               "session_id": session_id, "status": "running"}
        prompt = build_judge_prompt(case, source or "(source not available)", after, self.rubric)

        for attempt in range(1, self.max_attempts + 1):
            try:
                self.client.budget.guard(1)
                chat = self.client.chat_sync(
                    session_id, prompt, model_tier=config.MODEL_TIER,
                    thinking_depth=config.THINKING_DEPTH,
                )
            except BudgetExceeded as exc:
                out.update({"status": "failed", "error": str(exc)})
                return out
            except SuperDocsError as exc:
                out.update({"status": "failed", "error": str(exc)})
                return out
            out["usage"] = chat.get("usage")
            out["attempts"] = attempt
            response_text = chat.get("response") or ""
            payload = extract_json_from_text(response_text)
            if payload:
                out["response_preview"] = response_text[:400]
                scores = payload.get("scores") or {}
                evidence = payload.get("evidence") or {}
                invalid = [d for d, s in scores.items() if not valid_score(s)]
                if not invalid:
                    sheet = {
                        "case_id": case_id,
                        "rater": "auto",
                        "provider": "superdocs",
                        "scores": {d: scores[d] for d, _ in DIMENSIONS},
                        "evidence": {d: (evidence.get(d) or "") for d, _ in DIMENSIONS},
                        "difficulty": case["difficulty"],
                        "instruction": case["instruction"],
                    }
                    _save_sheet(sheet, config.AUTO_DIR)
                    out.update({"status": "completed", "scores": sheet["scores"]})
                    return out
                out.update({"status": "failed", "error": f"invalid scores for {invalid}",
                            "response": response_text[:1000]})
                return out
            out["response_preview"] = response_text[:400]

        out.update({"status": "failed",
                    "error": f"no JSON after {self.max_attempts} attempts",
                    "response": (chat.get("response") or "")[:2000]})
        return out

    def judge_all(self, case_ids: Optional[list[str]] = None) -> dict:
        from .pipeline import load_cases

        summary = {"results": [], "failed": []}
        for case in load_cases():
            if case_ids and case["case_id"] not in case_ids:
                continue
            res = self.judge_case(case)
            summary["results"].append(res)
            if res["status"] != "completed":
                summary["failed"].append(res)
        return summary


def get_judge():
    if config.JUDGE_PROVIDER == "superdocs":
        return AutoJudge()
    return GeminiJudge()


def save_human_scores(case_id: str, scores: dict, evidence: dict, judge_name: str = "human-1") -> dict:
    """Validate and persist one human judge's score sheet.

    Uses build_score_sheet, which rejects missing dimensions and out-of-range
    scores, so a partial or malformed form submission cannot create a sheet
    the analysis would silently drop."""
    sheet = build_score_sheet(case_id, judge_name, scores, evidence)
    path = config.HUMAN_DIR / f"{case_id}.json"
    path.write_text(json.dumps(sheet, indent=2), encoding="utf-8")
    return sheet


def load_score_sheets(rater: str) -> dict:
    """rater: 'human' or 'auto' -> {case_id: sheet}"""
    base = config.HUMAN_DIR if rater == "human" else config.AUTO_DIR
    sheets = {}
    for path in sorted(base.glob("*.json")):
        sheets[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return sheets


def load_all_sheets() -> tuple[dict, dict]:
    return load_score_sheets("human"), load_score_sheets("auto")