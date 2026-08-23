"""
CLI: parse an officer's RFE notice, match each request against what the
original petition already argued, identify new evidence needed from an
evidence catalog, assemble a numbered exhibit list, draft a response
section per request via the real SuperDocs API (one running
document/session, one turn per request), then export the assembled
response with a coverage checklist proving every request in the notice
was answered -- and by what.

Usage:
    export SUPERDOCS_API_KEY=sk_...
    python -m rfe_response_builder.generate \
        --notice data/sample_rfe_notice.txt \
        --petition data/sample_petition_arguments.json \
        --new-evidence data/sample_new_evidence.json \
        --case-id CASE-2002 --client-name "Marco Alvarez" \
        --out out/

Pass --dry-run to parse, match, and print the drafting instructions and
exhibit list WITHOUT calling the SuperDocs API or spending operations --
useful for a paralegal to sanity-check before committing to a run.

If SUPERDOCS_API_KEY is unset, pass --agent-signup to sign up a fresh
free SuperDocs agent account first.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

import requests

from .classify import RFECategory, classify, extract_response_deadline
from .consistency import check_cross_item_consistency
from .embeddings import get_default_provider
from .firm_templates import FirmTemplate, apply_firm_customization, load_firm_template
from .grounding import check_grounding
from .injection_guard import scan_all_inputs_for_injection_risk
from .judge import QualityVerdict, grade_draft
from .logging_config import configure_logging, set_case_id, set_request_id
from .progress import ProgressStore
from .rfe import (
    Exhibit,
    NewEvidenceCatalog,
    NewEvidenceEntry,
    PetitionArgument,
    PriorPetition,
    arguments_from_free_text,
    build_coverage_checklist,
    build_exhibit_list,
    build_response_instruction,
    is_substantive_reply,
    new_evidence_note_from_entries,
    parse_rfe_notice,
    sanitize_case_id,
)
from .schemas import validate_evidence_json, validate_petition_json
from .superdocs_client import SuperDocsClient, SuperDocsError

logger = logging.getLogger("rfe_response_builder")


def load_petition(path: Path) -> PriorPetition:
    raw = json.loads(path.read_text())
    validate_petition_json(raw)
    return PriorPetition(
        arguments=[
            PetitionArgument(topic_id=a["topic_id"], text=a["text"], source_ref=a["source_ref"])
            for a in raw["arguments"]
        ]
    )


def load_supporting_documents(paths: list[Path]) -> list[PetitionArgument]:
    """Multi-document ingestion: any number of free-text supporting
    documents (petition letter, employer letter, expert opinion, etc.) get
    parsed into candidate arguments and merged onto the structured
    petition. Deliberately paragraph-level keyword matching (see
    `arguments_from_free_text`'s docstring) rather than embeddings, so
    every match traces to a real paragraph in a real uploaded document."""
    args: list[PetitionArgument] = []
    for p in paths:
        args.extend(arguments_from_free_text(p.name, p.read_text()))
    return args


def load_new_evidence_catalog(path: Path | None) -> NewEvidenceCatalog:
    """New-evidence identification is catalog-driven, not invented: the
    tool only ever surfaces evidence *categories* that were supplied to
    it in this file, matched deterministically against each request's
    keywords. If no catalog is supplied, evidence identification is
    simply skipped (empty catalog) rather than fabricated."""
    if path is None:
        return NewEvidenceCatalog()
    raw = json.loads(path.read_text())
    validate_evidence_json(raw)
    return NewEvidenceCatalog(
        entries=[
            NewEvidenceEntry(
                topic_id=e["topic_id"],
                description=e["description"],
                exhibit_label=e["exhibit_label"],
            )
            for e in raw["entries"]
        ]
    )


def agent_signup(cred_path: Path | None = None) -> str:
    """Signs up a free SuperDocs agent account. Retries transient (429/5xx)
    failures with the same backoff policy as SuperDocsClient -- this call
    happens before a SuperDocsClient exists, so it can't reuse
    `_request_with_retry` directly, but should not be less resilient than
    every other network call in this package.

    `cred_path` defaults to `~/.superdocs/agent_credentials.json` (the
    CLI's actual behavior) but can be overridden -- this exists so tests
    can verify the write behavior without touching the real home
    directory of whatever machine runs them."""
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.post(
                "https://api.superdocs.app/v1/agents/signup",
                json={"terms_accepted": True, "agent_name": "rfe-response-builder"},
                timeout=30,
            )
            if resp.status_code >= 400:
                if resp.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning("agent-signup call failed (status=%s, attempt=%d/3); retrying in %.1fs",
                                   resp.status_code, attempt + 1, delay)
                    time.sleep(delay)
                    continue
                # Non-retryable (any 4xx other than 429) or retries
                # exhausted -- raise immediately rather than falling
                # through to resp.raise_for_status(), whose
                # requests.HTTPError would otherwise be caught by the
                # broad `except requests.RequestException` below and
                # retried anyway, wasting time on a request that can
                # never succeed (e.g. a malformed request body).
                raise SuperDocsError(f"agent signup failed: HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            key = data["api_key"]
            target_path = cred_path or (Path.home() / ".superdocs" / "agent_credentials.json")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(data, indent=2))
            logger.info("Agent-signed-up SuperDocs account created. Key saved to %s", target_path)
            return key
        except requests.RequestException as e:
            last_error = e
            if attempt < 2:
                delay = 1.0 * (2 ** attempt)
                logger.warning("agent-signup call raised %s (attempt=%d/3); retrying in %.1fs", e, attempt + 1, delay)
                time.sleep(delay)
    raise SuperDocsError(f"agent signup failed after retries: {last_error}")


def plan_response(notice_text: str, petition: PriorPetition, evidence_catalog: NewEvidenceCatalog):
    """Pure planning step shared by --dry-run and the real run: parses the
    notice, matches each request against the prior petition and the
    evidence catalog, and assembles the exhibit list. No network calls.
    Also computes `fuzzy_matches` (stemmed-keyword suggestions, see
    `PriorPetition.fuzzy_matches`) for any request the strict matcher
    found nothing for -- these are surfaced to the reviewer as unverified
    suggestions, never used as citations."""
    requests_list = parse_rfe_notice(notice_text)
    if not requests_list:
        raise ValueError("No RFE requests could be parsed from the notice -- aborting rather than exporting an empty response.")

    petition_matches = {r.request_id: petition.best_matches(r) for r in requests_list}
    evidence_matches = {r.request_id: evidence_catalog.best_matches(r) for r in requests_list}
    # One shared embedding provider for the whole run: when a real
    # embeddings API is configured (EMBEDDINGS_API_KEY -- see
    # embeddings.py), this lets APIEmbeddingProvider's in-memory cache
    # actually pay off -- the same petition argument texts get embedded
    # once and reused across every RFE item's semantic lookup, instead of
    # re-embedding them per item.
    embedding_provider = get_default_provider()
    # Tiered unverified suggestions: fuzzy (stemmed) tried first, semantic
    # (embeddings-based) only if fuzzy found nothing -- see
    # PriorPetition.unverified_suggestions. Stored as {request_id: (tier, matches)}.
    fuzzy_suggestions = {
        r.request_id: (
            petition.unverified_suggestions(r, provider=embedding_provider)
            if not petition_matches[r.request_id] else ("none", [])
        )
        for r in requests_list
    }
    exhibits = build_exhibit_list(requests_list, evidence_matches)
    return requests_list, petition_matches, evidence_matches, exhibits, fuzzy_suggestions


def dry_run(notice_text: str, petition: PriorPetition, evidence_catalog: NewEvidenceCatalog,
            firm_template: FirmTemplate | None = None) -> int:
    requests_list, petition_matches, evidence_matches, exhibits, fuzzy_suggestions = plan_response(
        notice_text, petition, evidence_catalog
    )
    classification = classify(notice_text)
    profile = classification.profile
    print(f"Parsed {len(requests_list)} RFE item(s). No SuperDocs calls made (--dry-run).\n")

    # Prompt-injection risk scan (heuristic -- see injection_guard.py):
    # runs once across every uploaded document, BEFORE anything gets sent
    # to SuperDocs, since the whole point is to catch this before
    # drafting happens at all.
    injection_flags = scan_all_inputs_for_injection_risk(
        notice_text=notice_text, petition=petition, evidence_catalog=evidence_catalog, firm_template=firm_template,
    )
    if injection_flags:
        print("⚠ Possible prompt-injection phrasing detected in uploaded material "
              "(heuristic check -- review the flagged source before proceeding):")
        for source, result in injection_flags:
            print(f"  - {source}: {', '.join(result.matched_labels)}")
        print()

    deadline = extract_response_deadline(notice_text)
    if deadline.found:
        print(f"⚠ Response deadline detected: {deadline.days} days "
              f"(matched: \"{deadline.matched_sentence}\") -- verify the exact date against the notice.\n")
    else:
        print("⚠ No response deadline phrase was detected automatically -- "
              "check the notice by hand for the response window.\n")
    if classification.category != RFECategory.UNKNOWN:
        print(f"Detected filing type: {profile.display_name} "
              f"(heuristic keyword match, score={classification.score}, "
              f"signals: {', '.join(classification.matched_signals)}) -- verify before relying on this.")
        print(profile.legal_framework_note)
        print()
    for r in requests_list:
        prior = petition_matches[r.request_id]
        prior_arg = prior[0] if prior else None
        evidence = evidence_matches[r.request_id]
        note = new_evidence_note_from_entries(evidence)
        framework_note = profile.legal_framework_note if classification.category != RFECategory.UNKNOWN else None
        instruction = build_response_instruction(r, prior_arg, note, legal_framework_note=framework_note)
        instruction = apply_firm_customization(instruction, firm_template, classification.category.value)
        print(f"--- Item {r.request_id} ---")
        print(instruction)
        if len(prior) > 1:
            print(f"(additional prior-petition matches not cited above: "
                  f"{', '.join(p.source_ref for p in prior[1:])})")
        if not prior:
            tier, matches = fuzzy_suggestions.get(r.request_id, ("none", []))
            if matches:
                suggestions = ", ".join(f"{arg.source_ref} ({conf:.0%})" for arg, conf in matches)
                label = "stemmed-keyword" if tier == "fuzzy" else "semantic-similarity-only"
                print(f"(no exact prior-petition match; possible related argument, UNVERIFIED, "
                      f"{label}, not cited: {suggestions})")
        print()
    if exhibits:
        print("--- Exhibit List ---")
        for ex in exhibits:
            print(f"Exhibit {ex.number} ({ex.label}): {ex.description} "
                  f"[supports item(s): {', '.join(ex.request_ids)}]")
    else:
        print("--- Exhibit List --- (none identified from the supplied evidence catalog)")
    return 0


def build_response_packet(client: SuperDocsClient, session_id: str, case_id: str, client_name: str,
                           notice_text: str, petition: PriorPetition, out_dir: Path,
                           evidence_catalog: NewEvidenceCatalog | None = None,
                           resume: bool = True, firm_template: FirmTemplate | None = None) -> tuple[Path, list]:
    evidence_catalog = evidence_catalog or NewEvidenceCatalog()
    requests_list, petition_matches, evidence_matches, exhibits, _fuzzy_suggestions = plan_response(
        notice_text, petition, evidence_catalog
    )
    classification = classify(notice_text)
    framework_note = (
        classification.profile.legal_framework_note if classification.category != RFECategory.UNKNOWN else None
    )
    if classification.category != RFECategory.UNKNOWN:
        logger.info("session %s: detected filing type %s (score=%d, signals=%s)",
                    session_id, classification.category.value, classification.score, classification.matched_signals)

    # Prompt-injection risk scan (heuristic -- see injection_guard.py):
    # runs once, BEFORE any SuperDocs call is made, across every uploaded
    # document that will end up embedded in a drafting instruction.
    injection_flags = scan_all_inputs_for_injection_risk(
        notice_text=notice_text, petition=petition, evidence_catalog=evidence_catalog, firm_template=firm_template,
    )
    if injection_flags:
        for source, result in injection_flags:
            logger.warning("possible prompt-injection phrasing detected in %s: %s",
                            source, ", ".join(result.matched_labels))
        print("⚠ Possible prompt-injection phrasing detected in uploaded material "
              "(heuristic check -- review the flagged source before proceeding):")
        for source, result in injection_flags:
            print(f"  - {source}: {', '.join(result.matched_labels)}")
        print()

    answered_ids: set[str] = set()
    safe_case_id = sanitize_case_id(case_id)

    # Resumable drafting: if a previous call for this exact session_id got
    # partway through (crash, worker recycle, network partition) before
    # finishing, `progress` already has outcomes for some request_ids.
    # `resume=False` lets a caller force a clean re-draft of every item
    # for this session_id instead (e.g. an explicit "start over" action).
    progress = ProgressStore(session_id)
    prior_progress = progress.load() if resume else {}
    if prior_progress:
        logger.info(
            "session %s: resuming drafting run -- %d/%d item(s) already recorded from a prior attempt",
            session_id, len(prior_progress), len(requests_list),
        )

    already_open = bool(prior_progress)
    if not already_open:
        # Turn 0: open the response document with a header. Skipped on
        # resume -- the document already exists in this session from the
        # earlier attempt, and re-sending this would duplicate the title.
        client.chat(
            session_id=session_id,
            message=(
                f"Start a new document titled 'RFE Response — {client_name} ({case_id})'. "
                f"Add a one-paragraph introduction stating this responds to the agency's "
                f"Request for Evidence, addressing each numbered item below in turn. "
                f"Do not draft the responses yet -- just the title and introduction."
            ),
        )

    # One turn per request -- keeps each edit auditable/reviewable and
    # keeps a single request's drafting failure from blocking the rest.
    # Transient SuperDocs errors are retried inside client.chat(); a
    # failure that survives those retries, OR a reply that comes back but
    # isn't a substantive answer (e.g. a hedge/refusal), lands here as
    # NOT ANSWERED -- a 200 response is necessary but not sufficient.
    ungrounded_by_request: dict[str, list[str]] = {}
    weak_by_request: dict[str, str] = {}
    for r in requests_list:
        set_request_id(r.request_id)
        done = prior_progress.get(r.request_id)
        if done is not None:
            if done.answered:
                answered_ids.add(r.request_id)
            logger.info("request %s: already recorded from a prior attempt (answered=%s) -- skipping redraft",
                        r.request_id, done.answered)
            continue

        prior_matches = petition_matches[r.request_id]
        prior_arg = prior_matches[0] if prior_matches else None
        note = new_evidence_note_from_entries(evidence_matches[r.request_id])
        instruction = build_response_instruction(r, prior_arg, note, legal_framework_note=framework_note)
        instruction = apply_firm_customization(instruction, firm_template, classification.category.value)
        try:
            result = client.chat(
                session_id=session_id, message=instruction,
                idempotency_key=f"{session_id}:{r.request_id}",
            )
            if is_substantive_reply(result.reply_text):
                answered_ids.add(r.request_id)
                progress.record(r.request_id, answered=True, reply_text=result.reply_text)
                # Fact-grounding check (heuristic -- see grounding.py). This
                # is the CLI's non-interactive path, so there's no human
                # review UI to show flags in before export the way the
                # webapp's review.html does -- instead, flags are logged
                # loudly and printed in a post-run summary (see below), so
                # an attorney reviewing the exported .docx (still required
                # regardless -- this tool never claims to replace that
                # review) knows exactly which sections to double-check first.
                source_texts = [r.text]
                if prior_arg:
                    source_texts.append(prior_arg.text)
                source_texts.extend(e.description for e in evidence_matches[r.request_id])
                grounding = check_grounding(result.reply_text, source_texts)
                if grounding.ungrounded_facts:
                    ungrounded_by_request[r.request_id] = grounding.ungrounded_facts
                    logger.warning("request %s: %d possibly-unsupported detail(s) in draft -- %s",
                                    r.request_id, len(grounding.ungrounded_facts), grounding.ungrounded_facts)

                # LLM-as-judge quality gate (see judge.py) -- OPT-IN via
                # QUALITY_GATE_ENABLED, same flag and same "separate
                # grading session, never pollute the drafting
                # conversation" design as review.py's start_review. Like
                # the grounding check above, flags surface via a logged
                # warning and the post-run summary printed below, since
                # this path has no review UI to show them in before export.
                if os.environ.get("QUALITY_GATE_ENABLED", "").lower() in {"1", "true", "yes"}:
                    grading = grade_draft(client, f"{session_id}-grading-{r.request_id}", r.text, result.reply_text)
                    if grading.verdict == QualityVerdict.WEAK:
                        weak_by_request[r.request_id] = grading.reasoning
                        logger.warning("request %s: quality gate flagged draft as WEAK -- %s",
                                        r.request_id, grading.reasoning)
            else:
                logger.warning(
                    "request %s: SuperDocs call succeeded but reply looks like a "
                    "non-answer -- marking NOT ANSWERED: %.120s",
                    r.request_id, result.reply_text,
                )
                progress.record(r.request_id, answered=False)
        except SuperDocsError as e:
            logger.error("request %s: FAILED to draft after retries -- %s", r.request_id, e)
            # Deliberately NOT recorded as progress: a transient failure
            # here should be retried on the next resume attempt, not
            # permanently frozen as "not answered" the way a genuine
            # non-substantive reply is.
    set_request_id(None)

    if ungrounded_by_request:
        print("\n⚠ Possibly-unsupported detail(s) flagged in the following section(s) "
              "(heuristic check -- verify against the record before relying on the exported document):")
        for rid, facts in ungrounded_by_request.items():
            print(f"  - Item {rid}: {', '.join(facts)}")
        print()

    if weak_by_request:
        print("⚠ Quality gate flagged the following section(s) as possibly NOT directly "
              "addressing the officer's concern (heuristic model judgment -- verify before relying "
              "on the exported document):")
        for rid, reasoning in weak_by_request.items():
            print(f"  - Item {rid}: {reasoning}")
        print()

    # Cross-item consistency check (heuristic -- see consistency.py): runs
    # once across every answered item's recorded text (including items
    # answered on a PRIOR attempt and skipped this run via resume -- see
    # progress.py -- since a contradiction between an old and new draft
    # is just as real as one between two drafts from the same run).
    drafted_texts = [(rid, p.reply_text) for rid, p in progress.load().items() if p.answered and p.reply_text]
    consistency_flags = check_cross_item_consistency(drafted_texts)
    if consistency_flags:
        print("⚠ Possible cross-item inconsistency detected (heuristic check -- verify against the "
              "record before relying on the exported document):")
        for flag in consistency_flags:
            print(f"  - Items {flag.request_id_a} and {flag.request_id_b} both mention "
                  f"\"{flag.shared_entity}\" but state different details: "
                  f"{', '.join(flag.facts_a)} vs {', '.join(flag.facts_b)}")
        print()

    coverage = build_coverage_checklist(
        requests_list, petition_matches, answered_ids,
        evidence_matches=evidence_matches, exhibits=exhibits,
    )

    def _checklist_line(row) -> str:
        status = "ANSWERED" if row.answered else "NOT ANSWERED"
        line = f"- Item {row.request_id}: {status} (section: {row.response_section})"
        if row.matched_prior_arguments:
            line += f" (prior petition: {'; '.join(row.matched_prior_arguments)})"
        else:
            line += " (new argument, no prior petition match)"
        if row.exhibit_numbers:
            exhibits_str = ", ".join("Exh. " + str(n) for n in row.exhibit_numbers)
            line += f" (exhibits: {exhibits_str})"
        line += f" [evidence status: {row.evidence_status}]"
        return line

    checklist_lines = "\n".join(_checklist_line(row) for row in coverage)
    client.chat(
        session_id=session_id,
        message=(
            f"Append a final section titled 'Coverage Checklist' listing, verbatim, "
            f"exactly this mapping of every RFE item to whether it was answered "
            f"(do not alter the ANSWERED/NOT ANSWERED status for any item):\n{checklist_lines}"
        ),
    )

    if exhibits:
        exhibit_lines = "\n".join(
            f"- Exhibit {ex.number} ({ex.label}): {ex.description} "
            f"[supports item(s): {', '.join(ex.request_ids)}]"
            for ex in exhibits
        )
        client.chat(
            session_id=session_id,
            message=(
                f"Append a final section titled 'Exhibit List' listing, verbatim, "
                f"exactly this list of new exhibits accompanying the response:\n{exhibit_lines}"
            ),
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{safe_case_id}-rfe-response.docx"
    file_bytes = client.export(session_id=session_id, fmt="docx", filename=safe_case_id + "-rfe-response")
    out_path.write_bytes(file_bytes)

    _write_exhibit_manifest(out_dir, safe_case_id, exhibits)

    # Run completed (export succeeded) -- clear the resumability record
    # so a genuinely new run later for this session_id starts fresh
    # rather than inheriting this attempt's now-irrelevant progress.
    progress.clear()

    return out_path, coverage


def _write_exhibit_manifest(out_dir: Path, safe_case_id: str, exhibits: list[Exhibit]) -> Path:
    """Writes the exhibit list as machine-readable JSON alongside the
    .docx so a paralegal (or another tool, e.g. an exhibit-indexer build)
    can programmatically pull up what new evidence needs to be gathered
    and physically attached as numbered exhibits."""
    manifest_path = out_dir / f"{safe_case_id}-exhibit-manifest.json"
    manifest = [
        {
            "number": ex.number,
            "label": ex.label,
            "description": ex.description,
            "supports_request_ids": ex.request_ids,
        }
        for ex in exhibits
    ]
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notice", type=Path, required=True, help="Path to a plaintext RFE notice")
    parser.add_argument("--petition", type=Path, required=True, help="Path to prior petition arguments JSON")
    parser.add_argument("--supporting-doc", type=Path, action="append", default=[],
                         help="Path to a free-text supporting document (petition letter, employer letter, "
                              "expert opinion, etc.); repeatable. Parsed into candidate arguments and merged "
                              "with --petition (multi-document ingestion).")
    parser.add_argument("--new-evidence", type=Path, default=None,
                         help="Path to a new-evidence catalog JSON (optional; skipped if omitted)")
    parser.add_argument("--firm-template", type=Path, default=None,
                         help="Path to a firm template JSON (optional; see firm_templates.py) customizing "
                              "tone, filing-type-specific guidance, and a standard closing paragraph for "
                              "every drafted section")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--out", type=Path, default=Path("out"))
    parser.add_argument("--agent-signup", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                         help="Parse, match, and print instructions/exhibits without calling SuperDocs")
    parser.add_argument("--review", action="store_true",
                         help="Draft via the human-review gate (rfe_response_builder.review): each section is "
                              "shown in the terminal and must be explicitly approved before it counts as "
                              "answered or reaches the exported document. Mutually exclusive with --dry-run.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args(argv)

    configure_logging(default_level="DEBUG" if args.verbose else "INFO")
    set_case_id(args.case_id)

    notice_text = args.notice.read_text()
    petition = load_petition(args.petition)
    petition.arguments.extend(load_supporting_documents(args.supporting_doc))
    evidence_catalog = load_new_evidence_catalog(args.new_evidence)
    firm_template = load_firm_template(args.firm_template) if args.firm_template else None

    if args.dry_run:
        try:
            return dry_run(notice_text, petition, evidence_catalog, firm_template=firm_template)
        except ValueError as e:
            logger.error("FAILED: %s", e)
            return 1

    api_key = os.environ.get("SUPERDOCS_API_KEY")
    if not api_key and args.agent_signup:
        api_key = agent_signup()
    if not api_key:
        logger.error("No SUPERDOCS_API_KEY set and --agent-signup not passed. Aborting.")
        return 2

    client = SuperDocsClient(api_key=api_key)
    session_id = f"rfe-response-{args.case_id}"

    if args.review:
        try:
            return _run_interactive_review(client, session_id, args, notice_text, petition, evidence_catalog)
        except (SuperDocsError, ValueError) as e:
            logger.error("FAILED: %s", e)
            return 1

    try:
        out_path, coverage = build_response_packet(
            client, session_id, args.case_id, args.client_name, notice_text, petition, args.out,
            evidence_catalog=evidence_catalog, firm_template=firm_template,
        )
    except (SuperDocsError, ValueError) as e:
        logger.error("FAILED: %s", e)
        return 1

    unanswered = [row for row in coverage if not row.answered]
    logger.info("%s: wrote %s -- %d RFE items, %d unanswered", args.case_id, out_path, len(coverage), len(unanswered))
    if unanswered:
        logger.warning("some RFE items were not answered:")
        for row in unanswered:
            logger.warning("  - item %s: %s...", row.request_id, row.request_text[:80])
        return 1
    return 0


def _run_interactive_review(client: SuperDocsClient, session_id: str, args, notice_text: str,
                             petition: PriorPetition, evidence_catalog: NewEvidenceCatalog) -> int:
    """Terminal counterpart to the web app's /review page: drafts every
    item behind SuperDocs' approval gate, prints each one, and prompts
    for an explicit y/n (with optional feedback on rejection) before
    calling finalize_review. A human still has to say yes to every
    section -- this only changes where that human types their answer."""
    from .review import finalize_review, start_review  # local import: keeps generate.py's top-level
    # imports free of the review module for callers who only use the non-interactive path.

    session = start_review(client, session_id, args.case_id, args.client_name, notice_text, petition,
                            evidence_catalog=evidence_catalog)

    decisions: dict[str, dict] = {}
    print(f"\n{len(session.items)} RFE item(s) drafted for review. Nothing is exported until you approve below.\n")
    for item in session.items:
        print(f"--- Item {item.request_id} ({item.response_section}) ---")
        print(f"Officer's request: {item.request_text}")
        if item.status == "failed":
            print(f"DRAFTING FAILED: {item.reply_text}")
            decisions[item.request_id] = {"approve": False}
            continue
        print(item.reply_text)
        if item.prior_source_refs:
            print(f"Prior petition: {', '.join(item.prior_source_refs)}")
        elif item.fuzzy_suggestions:
            suggestions = ", ".join(f"{ref} ({conf:.0%})" for ref, conf in item.fuzzy_suggestions)
            label = "stemmed-keyword" if item.suggestion_tier == "fuzzy" else "semantic-similarity-only"
            print(f"No exact prior-petition match. Possible related argument (UNVERIFIED, {label}): {suggestions}")
        answer = input("Approve this section? [y/N]: ").strip().lower()
        approve = answer == "y"
        feedback = None
        if not approve:
            feedback = input("Optional feedback (sent back to SuperDocs, press enter to skip): ").strip() or None
        decisions[item.request_id] = {"approve": approve, "feedback": feedback}
        print()

    out_path, coverage = finalize_review(client, session, decisions, args.out)
    unanswered = [row for row in coverage if not row.answered]
    logger.info("%s: wrote %s -- %d RFE items, %d unanswered", args.case_id, out_path, len(coverage), len(unanswered))
    if unanswered:
        logger.warning("some RFE items were not answered (rejected or failed):")
        for row in unanswered:
            logger.warning("  - item %s: %s...", row.request_id, row.request_text[:80])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
