"""
llm_client.py -- direct Groq API calls, deliberately kept OUTSIDE SuperDocs.
This is the one piece of the system where an LLM is called directly rather
than through SuperDocs' chat/chat_async surface.

Why this call doesn't go through SuperDocs (see the architecture
discussion in the build chat): reference discovery is structured
classification -- "given these policy sections and this procedure, which
section pairs are IMPLEMENTS relationships, with what confidence and
evidence" -- not document editing. SuperDocs' API is built for editing
documents (chat -> proposed changes -> approve), and every one of those
calls is billable against the account's operations quota. Routing
classification through it would both be the wrong tool for the job and
burn quota on the one phase of the system that doesn't need SuperDocs at
all. Doing it as a plain Groq API call with forced structured (tool-call)
output keeps this phase at zero SuperDocs operations, regardless of how
many procedures a workspace has.

Groq exposes an OpenAI-compatible Chat Completions API (including
function/tool calling), so this client speaks that dialect rather than
Anthropic's Messages API.

Sync + `requests`-based, matching superdocs_client.py's style rather than
mixing async and sync HTTP clients in one codebase -- concurrency for the
Analyze References job pool is handled at the call-site with a
ThreadPoolExecutor (see main.py's analyze_references), same pattern
FastAPI itself uses for sync route handlers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import requests

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
# openai/gpt-oss-120b -- OpenAI's open-weight 120B model, served on Groq.
# Supports tool use + JSON schema mode, which is all this module needs
# (forced tool-calling for structured relationship output below). Kept as
# a plain constant rather than an os.environ read at import time -- main.py
# imports this module BEFORE calling load_dotenv(), so an env lookup here
# would always miss whatever's in .env. The actual GROQ_MODEL override (see
# LLMClient.__init__ below) is read lazily instead, same pattern already
# used for GROQ_API_KEY, so it correctly sees .env values.
#
# Also -- as of 08/16/26 Groq deprecated llama-3.3-70b-versatile (confirmed
# via console.groq.com/docs/deprecations), which had been the natural pick
# for a higher free-tier TPM ceiling. Groq's own recommended replacement is
# this same model (openai/gpt-oss-120b) or qwen/qwen3.6-27b -- both capped
# at the same 8,000 TPM free-tier limit (console.groq.com/docs/rate-limits).
# So the fix for large requests isn't a model swap, it's request batching
# (see GROQ_FREE_TPM_LIMIT and _plan_batches below).
DEFAULT_MODEL = "openai/gpt-oss-120b"

# Free-tier TPM ceiling shared by every tool-calling-capable Groq model
# available to this project (gpt-oss-120b/20b/safeguard-20b, qwen3.6-27b) --
# confirmed via console.groq.com/docs/rate-limits, Aug 2026. This is
# enforced per REQUEST, not just as a rolling average: a single call whose
# estimated prompt + max_tokens exceeds it is rejected outright with a 413
# rate_limit_exceeded (confirmed against a live error: Requested 19615 vs
# Limit 8000). Raising max_tokens to avoid truncation (see
# _MAX_TOKENS_PER_BATCH below) is only safe if the PROMPT is kept small
# enough to leave room under this ceiling -- which is what batching by
# procedure-section groups (_plan_batches, discover_references) is for.
GROQ_FREE_TPM_LIMIT = 8000
_TPM_SAFETY_MARGIN = 0.9  # headroom for _estimate_tokens being a heuristic, not a real tokenizer
_EFFECTIVE_TPM_BUDGET = int(GROQ_FREE_TPM_LIMIT * _TPM_SAFETY_MARGIN)

# Output budget per batch. Each relationship in the tool-call JSON is small
# (two ids, a confidence float, a <=25-word reason) but ids are UUIDs
# (tokenize into several pieces each) and JSON syntax adds overhead --
# ~150-200 tokens/relationship is a safe per-item estimate. 3000 comfortably
# covers what one batch (a handful of procedure sections against the full
# policy) can realistically produce, while leaving most of the TPM budget
# for the policy context that's repeated in every batch.
_MAX_TOKENS_PER_BATCH = 3000


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token for English prose). Good enough
    for TPM budgeting -- not meant to match Groq's actual tokenizer exactly,
    which is why _TPM_SAFETY_MARGIN exists as a buffer against the estimate
    being off in either direction."""
    return max(1, len(text) // 4)

# Forced structured output: a single tool whose parameters schema IS the
# answer shape we want. tool_choice pins the model to calling exactly this
# tool, which is the reliable way to get parseable JSON back from a
# chat-style API rather than asking it to "please respond in JSON" in the
# prompt text.
_REFERENCE_TOOL = {
    "type": "function",
    "function": {
        "name": "report_references",
        "description": (
            "Report every place where a section of the PROCEDURE document implements "
            "a section of the POLICY document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "procedure_section_id": {
                                "type": "string",
                                "description": "The id of the procedure section, exactly as given in the input.",
                            },
                            "policy_section_id": {
                                "type": "string",
                                "description": "The id of the policy section it implements, exactly as given in the input.",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "0.0-1.0 confidence that this is a genuine IMPLEMENTS relationship.",
                            },
                            "reason": {
                                "type": "string",
                                "description": (
                                    "ONE short sentence, under 25 words: the specific evidence linking the two "
                                    "sections. Be terse -- a large policy/procedure pair can produce dozens of "
                                    "relationships in one response, and a verbose reason on every one risks "
                                    "truncating the whole response before it finishes. Describe the shared "
                                    "requirement or concept in your own words (e.g. 'both cover minimum-necessary "
                                    "access review'). Do NOT cite a section, clause, or item number anywhere in "
                                    "this sentence -- not even the number of the two sections you were given -- "
                                    "unless that exact number literally appears in the CONTENT_TEXT you were shown "
                                    "for one of them. Never invent a citation."
                                ),
                            },
                        },
                        "required": ["procedure_section_id", "policy_section_id", "confidence", "reason"],
                    },
                }
            },
            "required": ["relationships"],
        },
    },
}


class LLMError(RuntimeError):
    """Raised for any non-2xx response from the Groq API, or a response
    that doesn't contain the expected tool_calls block."""


@dataclass
class SectionInput:
    """One section fed into a reference-discovery call. `id` here is our
    own stable Section.id -- the model is asked to echo it back verbatim,
    never to invent identifiers."""

    id: str
    number: str
    title: str
    content_text: str


@dataclass
class DiscoveredReference:
    procedure_section_id: str
    policy_section_id: str
    confidence: float
    reason: str


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = DEFAULT_MODEL


@dataclass
class ReferenceDiscoveryResult:
    relationships: list[DiscoveredReference] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=LLMUsage)


def _build_prompt(
    policy_title: str,
    policy_sections: list[SectionInput],
    procedure_title: str,
    procedure_sections: list[SectionInput],
) -> str:
    def render(label: str, title: str, sections: list[SectionInput]) -> str:
        lines = [f"{label}: {title}", ""]
        for sec in sections:
            lines.append(f"[id={sec.id}] Section {sec.number} -- {sec.title}")
            lines.append(sec.content_text)
            lines.append("")
        return "\n".join(lines)

    return (
        "You are analyzing a healthcare policy document and one procedure document that is "
        "supposed to operationalize parts of it.\n\n"
        + render("POLICY", policy_title, policy_sections)
        + "\n"
        + render("PROCEDURE", procedure_title, procedure_sections)
        + "\n"
        "For every procedure section that implements one or more policy sections, report the "
        "relationship via the report_references tool. A procedure section can implement more than "
        "one policy section, and a policy section can be implemented by more than one procedure "
        "section -- report every genuine pair, not just the strongest match. Do not report a "
        "relationship unless the procedure section's content actually operationalizes something "
        "the policy section requires. Use the exact `id` values given above, never invent your own. "
        "When writing the `reason` for a relationship, never cite a section, clause, or item number "
        "that does not literally appear in the CONTENT_TEXT shown above for that section -- if you "
        "are not quoting a number straight from the text, don't include a number at all."
    )


def _render_procedure_block(sec: SectionInput) -> str:
    """Same rendering _build_prompt uses for one procedure section -- kept
    separate so _plan_batches can cost a section without building a whole
    prompt just to measure it."""
    return f"[id={sec.id}] Section {sec.number} -- {sec.title}\n{sec.content_text}\n"


def _plan_batches(
    policy_title: str,
    policy_sections: list[SectionInput],
    procedure_title: str,
    procedure_sections: list[SectionInput],
) -> list[list[SectionInput]]:
    """
    Split procedure_sections into batches so each batch's prompt (full
    policy context + just that batch of procedure sections) plus
    _MAX_TOKENS_PER_BATCH stays under _EFFECTIVE_TPM_BUDGET.

    The full policy is deliberately repeated in every batch rather than
    filtered -- correct attribution needs the whole policy, not a guessed
    subset (the original v1 decision, unchanged). Batching only splits the
    PROCEDURE side, which is what actually grows unboundedly with a large
    procedure document.

    Degenerate case: if the policy alone is already close to/over budget,
    every batch ends up holding exactly one procedure section (still
    correct, just one Groq call per section instead of per handful --
    slower but never silently over the TPM ceiling).
    """
    fixed_overhead = _estimate_tokens(
        _build_prompt(policy_title, policy_sections, procedure_title, [])
    )
    available_for_procedure = _EFFECTIVE_TPM_BUDGET - fixed_overhead - _MAX_TOKENS_PER_BATCH

    batches: list[list[SectionInput]] = []
    current: list[SectionInput] = []
    current_tokens = 0
    for sec in procedure_sections:
        sec_tokens = _estimate_tokens(_render_procedure_block(sec))
        if current and current_tokens + sec_tokens > max(available_for_procedure, 0):
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(sec)
        current_tokens += sec_tokens
    if current:
        batches.append(current)
    return batches


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: int = 90):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("LLMClient requires a GROQ_API_KEY")
        self.model = model or os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_MODEL
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def discover_references(
        self,
        policy_title: str,
        policy_sections: list[SectionInput],
        procedure_title: str,
        procedure_sections: list[SectionInput],
    ) -> ReferenceDiscoveryResult:
        """
        Analyze References' entry point. Splits procedure_sections into
        TPM-budgeted batches (see _plan_batches) and makes one Groq call
        per batch, each carrying the FULL policy context (needed for
        correct attribution -- the "send all policy sections, not a
        filtered subset" v1 decision, unchanged) plus just that batch's
        procedure sections. Results are merged into a single result so
        this method's signature/behavior is unchanged from the caller's
        perspective (main.py) even though it may now be >1 HTTP call.

        Batching exists because a single big call can legitimately need
        more max_tokens than fits under Groq's free-tier TPM ceiling
        alongside its own prompt -- confirmed via a live 413
        rate_limit_exceeded error (19615 requested vs 8000 limit) that
        appeared right after fixing a *separate*, also-confirmed-live 400
        tool_use_failed truncation bug by raising max_tokens. Shrinking the
        prompt per call (via batching) is what lets both fixes coexist.

        Raises LLMError on any batch's failure rather than returning a
        partial/guessed result -- the caller (main.py) decides whether to
        mark the AnalysisJob FAILED or retry.
        """
        batches = _plan_batches(policy_title, policy_sections, procedure_title, procedure_sections)
        if not batches:
            return ReferenceDiscoveryResult(relationships=[], usage=LLMUsage(model=self.model))

        all_relationships: list[DiscoveredReference] = []
        total_input_tokens = 0
        total_output_tokens = 0
        last_model = self.model
        for batch in batches:
            result = self._discover_references_batch(policy_title, policy_sections, procedure_title, batch)
            all_relationships.extend(result.relationships)
            total_input_tokens += result.usage.input_tokens
            total_output_tokens += result.usage.output_tokens
            last_model = result.usage.model

        return ReferenceDiscoveryResult(
            relationships=all_relationships,
            usage=LLMUsage(input_tokens=total_input_tokens, output_tokens=total_output_tokens, model=last_model),
        )

    def _discover_references_batch(
        self,
        policy_title: str,
        policy_sections: list[SectionInput],
        procedure_title: str,
        procedure_sections_batch: list[SectionInput],
    ) -> ReferenceDiscoveryResult:
        """The actual Groq HTTP call for one batch. Only the PROCEDURE side
        is batched -- policy_sections is always the full set, per
        discover_references' docstring."""
        prompt = _build_prompt(policy_title, policy_sections, procedure_title, procedure_sections_batch)
        payload: dict[str, Any] = {
            "model": self.model,
            # _plan_batches sized this batch's procedure content so that
            # (prompt tokens + _MAX_TOKENS_PER_BATCH) stays under the free-
            # tier TPM ceiling -- see GROQ_FREE_TPM_LIMIT's comment for why
            # this has to be a per-request budget, not just a big number.
            "max_tokens": _MAX_TOKENS_PER_BATCH,
            # gpt-oss-120b is a reasoning model: by default it spends part of
            # max_tokens on internal <reasoning> content BEFORE/WHILE writing
            # the actual tool-call JSON (console.groq.com/docs/reasoning).
            # Confirmed against a live 400 tool_use_failed where the visible
            # JSON cut off after only ~9 relationships -- well under
            # _MAX_TOKENS_PER_BATCH's raw size, because reasoning tokens ate
            # the rest of the budget first. reasoning_effort (unlike
            # include_reasoning, which only hides the field) actually caps
            # how many reasoning tokens get generated, freeing the budget for
            # the answer itself. "low" fits this task -- matching a procedure
            # section to the policy sections it implements is pattern-
            # matching over provided text, not multi-step deduction.
            "reasoning_effort": "low",
            "include_reasoning": False,
            "tools": [_REFERENCE_TOOL],
            "tool_choice": {"type": "function", "function": {"name": "report_references"}},
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = self._session.post(GROQ_API_URL, json=payload, timeout=self.timeout)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise LLMError(f"Groq API error {resp.status_code}: {body}")

        data = resp.json()
        usage_raw = data.get("usage") or {}
        usage = LLMUsage(
            input_tokens=usage_raw.get("prompt_tokens", 0),
            output_tokens=usage_raw.get("completion_tokens", 0),
            model=data.get("model", self.model),
        )

        choices = data.get("choices") or []
        message = choices[0].get("message", {}) if choices else {}
        tool_calls = message.get("tool_calls") or []
        tool_call = next((tc for tc in tool_calls if tc.get("function", {}).get("name") == "report_references"), None)
        if tool_call is None:
            raise LLMError(f"no report_references tool call in Groq response: {json.dumps(data)[:500]}")

        try:
            arguments = json.loads(tool_call["function"]["arguments"])
        except (KeyError, json.JSONDecodeError) as e:
            raise LLMError(f"could not parse tool call arguments from Groq response: {e}")

        raw_relationships = arguments.get("relationships", [])
        relationships = [
            DiscoveredReference(
                procedure_section_id=r["procedure_section_id"],
                policy_section_id=r["policy_section_id"],
                confidence=float(r["confidence"]),
                reason=r.get("reason", ""),
            )
            for r in raw_relationships
            if "procedure_section_id" in r and "policy_section_id" in r
        ]
        return ReferenceDiscoveryResult(relationships=relationships, usage=usage)
