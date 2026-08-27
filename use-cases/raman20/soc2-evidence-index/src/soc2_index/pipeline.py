from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from soc2_index import diff as diffmod
from soc2_index import render
from soc2_index.catalog import load_catalog, load_sample_catalog
from soc2_index.clock import generated_at as clock_generated
from soc2_index.ingest import IngestError, walk
from soc2_index.logutil import JsonlLogger
from soc2_index.map import apply as map_apply
from soc2_index.models import (
    DecisionRecord,
    EvidenceFile,
    EvidenceTab,
    IndexDiff,
    IndexDoc,
    Proof,
    RowChunkMap,
    RunState,
)
from soc2_index.paths import (
    default_catalog_path,
    mapping_rules_path,
    project_root,
    sample_catalog_path,
    skeleton_template_path,
)
from soc2_index.runstore import create_state_excl, load_json, sha256_file, write_json, write_text
from soc2_index.validate import ValidationError, attach_html_proof, build_index, live_ok, proof_local


class UsageError(Exception):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


class SuperDocsRunError(Exception):
    def __init__(self, message: str, code: int = 4) -> None:
        super().__init__(message)
        self.code = code


def materialize(
    evidence: Path,
    catalog_path: Path | None,
    *,
    sample: bool,
    org: str,
    period: str,
    generated_at: str,
    from_index: IndexDoc | None = None,
    from_run: str | None = None,
    to_run: str | None = None,
) -> tuple[IndexDoc, list[EvidenceFile], IndexDiff | None, Any]:
    if sample and catalog_path is None:
        catalog = load_sample_catalog()
    else:
        catalog = load_catalog(catalog_path or default_catalog_path())
    if from_index is not None and catalog.id != from_index.catalog_id:
        raise UsageError(
            f"catalog mismatch: --from has {from_index.catalog_id}, loaded {catalog.id}"
        )
    files = walk(evidence, mapping_rules_path())
    mapping = map_apply(catalog, files)
    index = build_index(catalog, mapping, org, period, generated_at)
    d: IndexDiff | None = None
    if from_index is not None:
        d = diffmod.compute(from_index, index, from_run or "from", to_run or "to")
    return index, files, d, mapping


def write_local_artifacts(
    out: Path,
    index: IndexDoc,
    files: list[EvidenceFile],
    mapping_ambiguous: list,
    diff_obj: IndexDiff | None,
) -> None:
    write_json(out / "index.json", index)
    write_json(out / "files.json", [f.model_dump(mode="json") for f in files])
    write_json(out / "ambiguous.json", [a.model_dump(mode="json") for a in mapping_ambiguous])
    write_json(out / "flagged.json", [f.model_dump(mode="json") for f in index.flagged])
    gaps = [r for r in index.rows if r.status == "GAP"]
    gap_md = "# Gaps\n\n" + "\n".join(f"- `{r.control_id}`: {r.gap_reason}" for r in gaps) + "\n"
    write_text(out / "gaps.md", gap_md)
    write_text(out / "index.html", render.html(index))
    write_text(out / "index.md", render.markdown(index))
    if diff_obj is not None:
        write_json(out / "diff.json", diff_obj)
        write_text(
            out / "diff.md",
            "# Diff\n\n"
            f"added: {len(diff_obj.added)}\n"
            f"removed: {len(diff_obj.removed)}\n"
            f"changed: {len(diff_obj.changed)}\n"
            f"renamed: {len(diff_obj.renamed)}\n"
            f"unchanged: {len(diff_obj.unchanged_ids)}\n",
        )


def _account_templates_path() -> Path:
    return project_root() / "runs" / "_account" / "templates.json"


def _extract_template_id(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for k in ("template_id", "id"):
        if payload.get(k):
            return str(payload[k])
    return None


def _upload_new_id(client, path: Path, session_id: str, open_mode: str, filename: str | None = None) -> tuple[str, dict]:
    from soc2_index.superdocs.session import document_id_of, focused_id, roster_docs

    before = {document_id_of(d) for d in roster_docs(client.list_documents(session_id)) if document_id_of(d)}
    payload = client.upload_document(path, session_id, open_mode, filename=filename)
    after_payload = client.list_documents(session_id)
    after = {document_id_of(d) for d in roster_docs(after_payload) if document_id_of(d)}
    new = after - before
    if len(new) == 1:
        return next(iter(new)), payload
    did = document_id_of(payload) or focused_id(payload)
    if did:
        return did, payload
    raise SuperDocsRunError("upload did not return a document_id")


def _ensure_template(client, logger: JsonlLogger) -> tuple[str | None, str]:
    from soc2_index.superdocs.session import listed_template_name

    local = skeleton_template_path()
    local_sha = sha256_file(local)
    acc = _account_templates_path()
    cached = None
    if acc.is_file():
        cached = load_json(acc)
    listed_name = "SOC2-Evidence-Index"
    template_id = None
    if (
        isinstance(cached, dict)
        and cached.get("local_sha256") == local_sha
        and cached.get("template_id")
    ):
        try:
            listing = client.list_templates()
            name = listed_template_name(listing, cached.get("template_id"))
            if name or cached.get("template_id"):
                template_id = cached.get("template_id")
                listed_name = name or cached.get("listed_name") or listed_name
                return template_id, listed_name
        except Exception as exc:
            logger.log("template_list_failed", error=str(exc))
    payload = client.upload_template(local)
    template_id = _extract_template_id(payload)
    try:
        listing = client.list_templates()
        listed_name = listed_template_name(listing, template_id) or listed_name
        raw_list = listing
    except Exception:
        raw_list = {}
        logger.log("warn", msg="template listed_name missing; using filename stem")
    rec = {
        "local_path": str(local.relative_to(project_root())),
        "local_sha256": local_sha,
        "template_id": template_id,
        "listed_name": listed_name,
        "raw_upload_response": payload,
        "raw_list_item": raw_list,
    }
    write_json(acc, rec)
    return template_id, listed_name


def _append_decision(path: Path, rec: DecisionRecord) -> None:
    existing: list = []
    if path.is_file():
        existing = load_json(path)
        if not isinstance(existing, list):
            existing = []
    existing.append(rec.model_dump(mode="json"))
    write_json(path, existing)


def _append_cost(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def settle_job(
    client,
    session_id: str,
    job: dict,
    index_document_id: str,
    *,
    out: Path,
    logger: JsonlLogger,
    generated_at: str,
) -> dict:
    from soc2_index.superdocs.hitl import (
        encode_approve_all,
        is_continue_prompt,
        pending_changes,
        usage_ops,
    )

    while True:
        job = client.wait(job)
        status = job.get("status")
        if status == "completed":
            ops = usage_ops(job)
            _append_cost(
                out / "cost.jsonl",
                {
                    "ts": generated_at,
                    "method": "POST",
                    "path": "/v1/chat/async",
                    "status": 200,
                    "ops_charged": ops,
                    "elapsed_ms": None,
                    "billable": bool(ops),
                },
            )
            return job
        if is_continue_prompt(job):
            _append_decision(
                out / "decisions.json",
                DecisionRecord(
                    ts=generated_at,
                    actor="pipeline",
                    kind="continue_prompt",
                    run_id=str(out),
                    job_id=job.get("job_id"),
                    approved=True,
                ),
            )
            job = client.continue_job(session_id, job["job_id"], True)
            continue
        changes = pending_changes(job)
        if not changes:
            raise SuperDocsRunError("awaiting_approval with no pending_changes and not continue_prompt")
        body = encode_approve_all(job["job_id"], changes, index_document_id=index_document_id)
        for ch in body.get("changes") or []:
            _append_decision(
                out / "decisions.json",
                DecisionRecord(
                    ts=generated_at,
                    actor="pipeline",
                    kind="superdocs_change",
                    run_id=str(out),
                    job_id=job.get("job_id"),
                    change_id=ch.get("change_id"),
                    document_id=index_document_id,
                    approved=bool(ch.get("approved")),
                ),
            )
        job = client.approve(session_id, body)


def _index_html(client, session_id: str, index_id: str) -> str:
    from soc2_index.superdocs.session import find_index_html

    client.focus(session_id, index_id)
    roster = client.list_documents(session_id, include_html=True)
    html = find_index_html(roster, index_id)
    if not html:
        raise SuperDocsRunError("could not fetch SuperDocs index HTML")
    return html


def _proof_html(html: str, index: IndexDoc, files: list[EvidenceFile], diff_obj: IndexDiff | None) -> tuple[Proof, RowChunkMap]:
    from soc2_index.superdocs.parse_index import parse

    files_payload = [f.model_dump(mode="json") for f in files]
    canonical = [r.row_id for r in index.rows]
    parsed = parse(html, files_payload, canonical)
    p = proof_local(index, files)
    p = attach_html_proof(p, [r.row_id for r in parsed.rows if r.row_id], canonical)
    p.dangling = list(parsed.dangling)
    p.overreach = list(parsed.overreach)
    if diff_obj is not None:
        p.diff_summary = diff_obj.summary
    cmap = RowChunkMap(
        index_document_id="",
        rows=dict(parsed.row_chunk_map),
        data_row_id_survived=parsed.data_row_id_survived,
    )
    return p, cmap


def refresh_evidence_tabs(
    client,
    session_id: str,
    index_id: str,
    files: list[EvidenceFile],
    old_tabs: list[dict],
    evidence_root: Path,
) -> list[dict]:
    current = {f.relative_path: f for f in files if not f.injection_flags}
    old_by = {t.get("relative_path"): t for t in old_tabs}
    new_tabs: list[dict] = []
    for path, rec in current.items():
        old = old_by.get(path)
        if old and old.get("sha256") == rec.sha256 and old.get("document_id"):
            new_tabs.append(old)
            continue
        if old and old.get("document_id"):
            try:
                client.close_document(session_id, old["document_id"])
            except Exception:
                pass
        did, _ = _upload_new_id(client, evidence_root / path, session_id, "background", Path(path).name)
        new_tabs.append(
            EvidenceTab(
                relative_path=path,
                sha256=rec.sha256,
                document_id=did,
                filename=Path(path).name,
            ).model_dump(mode="json")
        )
    for path, old in old_by.items():
        if path not in current and old.get("document_id"):
            try:
                client.close_document(session_id, old["document_id"])
            except Exception:
                pass
    client.focus(session_id, index_id)
    return new_tabs


def live_run(
    *,
    out: Path,
    evidence: Path,
    index: IndexDoc,
    files: list[EvidenceFile],
    diff_obj: IndexDiff | None,
    from_dir: Path | None,
    session_id: str,
    max_ops: int,
    wait_timeout: int,
    generated_at: str,
    api_key: str | None,
) -> None:
    from soc2_index.superdocs.client import Client, SuperDocsError
    from soc2_index.superdocs.parse_index import parse
    from soc2_index.superdocs.render_live import compact_payload, fill_prompt, surgical_prompt
    from soc2_index.superdocs.export import export_pair
    from soc2_index.superdocs.session import document_id_of, roster_docs

    logger = JsonlLogger(out / "log.jsonl")
    state_path = out / "state.json"
    state = RunState.model_validate(load_json(state_path))

    try:
        client = Client(api_key=api_key, logger=logger, wait_timeout=wait_timeout)
        template_id, listed_name = _ensure_template(client, logger)
        state.template_id = template_id
        state.listed_template_name = listed_name
        state.stage = "template"
        write_json(state_path, state)

        reuse = False
        old_tabs: list[dict] = []
        from_html = None
        chunk_map: dict[str, str] = {}
        if from_dir is not None:
            from_state_p = from_dir / "state.json"
            if from_state_p.is_file():
                prev = RunState.model_validate(load_json(from_state_p))
                if prev.session_id:
                    session_id = prev.session_id
                if prev.index_document_id:
                    try:
                        roster = client.list_documents(session_id)
                        ids = {document_id_of(d) for d in roster_docs(roster)}
                        if prev.index_document_id in ids:
                            reuse = True
                            state.index_document_id = prev.index_document_id
                    except SuperDocsError:
                        reuse = False
            tabs_p = from_dir / "superdocs" / "evidence_tabs.json"
            if tabs_p.is_file():
                raw = load_json(tabs_p)
                old_tabs = raw if isinstance(raw, list) else []
            map_p = from_dir / "superdocs" / "row_chunk_map.json"
            if map_p.is_file():
                chunk_map = dict(load_json(map_p).get("rows") or {})
            html_p = from_dir / "superdocs" / "index.html"
            if html_p.is_file():
                from_html = html_p.read_text(encoding="utf-8")

        state.session_id = session_id
        state.stage = "session"
        write_json(state_path, state)

        existing_html = out / "superdocs" / "index.html"
        if existing_html.is_file() and state.index_document_id:
            proof, cmap = _proof_html(
                existing_html.read_text(encoding="utf-8"), index, files, diff_obj
            )
            cmap.index_document_id = state.index_document_id
            write_json(out / "superdocs" / "row_chunk_map.json", cmap)
            write_json(out / "proof.json", proof)
            if live_ok(proof):
                logger.log("resume_proof_ok", session_id=session_id)
                state.stage = "ready_to_export"
                write_json(state_path, state)
                client.focus(session_id, state.index_document_id)
                from soc2_index.superdocs.export import export_pair

                export_pair(client, session_id, out / "export", logger)
                state.stage = "done"
                write_json(state_path, state)
                return

        if reuse and state.index_document_id:
            client.focus(session_id, state.index_document_id)
            tabs = refresh_evidence_tabs(
                client, session_id, state.index_document_id, files, old_tabs, evidence
            )
        else:
            skel = skeleton_template_path()
            if from_html:
                tmp = out / "superdocs" / "_reupload.html"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(from_html, encoding="utf-8")
                index_id, _ = _upload_new_id(client, tmp, session_id, "replace", "SOC2-Evidence-Index.html")
            else:
                index_id, _ = _upload_new_id(client, skel, session_id, "replace", "SOC2-Evidence-Index.html")
            state.index_document_id = index_id
            write_json(state_path, state)
            tabs = []
            for f in files:
                if f.injection_flags:
                    continue
                did, _ = _upload_new_id(
                    client, evidence / f.relative_path, session_id, "background", Path(f.relative_path).name
                )
                tabs.append(
                    EvidenceTab(
                        relative_path=f.relative_path,
                        sha256=f.sha256,
                        document_id=did,
                        filename=Path(f.relative_path).name,
                    ).model_dump(mode="json")
                )
            client.focus(session_id, index_id)

        write_json(out / "superdocs" / "evidence_tabs.json", tabs)
        index_id = state.index_document_id
        assert index_id

        html_now = _index_html(client, session_id, index_id)
        write_text(out / "superdocs" / "index.html", html_now)
        parsed_now = parse(html_now)
        if parsed_now.row_chunk_map:
            chunk_map = parsed_now.row_chunk_map
            write_json(
                out / "superdocs" / "row_chunk_map.json",
                RowChunkMap(index_document_id=index_id, rows=chunk_map).model_dump(mode="json"),
            )

        if state.ops_charged_this_run + 1 > max_ops:
            raise SuperDocsRunError(f"--max-ops {max_ops} would be exceeded by another chat")

        if state.job_id and state.stage in {"chat", "hitl"}:
            job = client.get_job(state.job_id)
        else:
            if diff_obj is not None and (diff_obj.added or diff_obj.removed or diff_obj.changed or diff_obj.renamed):
                neighbor = next(iter(chunk_map.values()), None)
                message = surgical_prompt(
                    index_id=index_id,
                    diff=diff_obj,
                    index=index,
                    chunk_map=chunk_map,
                    neighbor_chunk=neighbor,
                )
            else:
                compact = compact_payload(index)
                message = fill_prompt(index_id=index_id, listed_name=listed_name, compact_json=compact)
            job = client.chat_async(message, session_id, document_id=index_id)
            state.job_id = job.get("job_id")
            state.stage = "chat"
            write_json(state_path, state)

        job = settle_job(
            client,
            session_id,
            job,
            index_id,
            out=out,
            logger=logger,
            generated_at=generated_at,
        )
        state.ops_charged_this_run += int(((job.get("result") or {}).get("usage") or {}).get("ops_charged") or 0)
        write_json(state_path, state)

        html_after = _index_html(client, session_id, index_id)
        write_text(out / "superdocs" / "index.html", html_after)
        proof, cmap = _proof_html(html_after, index, files, diff_obj)
        cmap.index_document_id = index_id
        write_json(out / "superdocs" / "row_chunk_map.json", cmap)
        write_json(out / "proof.json", proof)

        if not live_ok(proof) and proof.invented:
            # one surgical delete of invented rows
            inv_chunks = [cmap.rows[i] for i in (proof.invented or []) if i in cmap.rows]
            if inv_chunks and state.ops_charged_this_run + 1 <= max_ops:
                msg = (
                    f"You are editing document_id={index_id} only. "
                    "Delete these invented table ROW chunks and no others: "
                    + ", ".join(inv_chunks)
                )
                job = client.chat_async(msg, session_id, document_id=index_id)
                state.job_id = job.get("job_id")
                write_json(state_path, state)
                job = settle_job(
                    client, session_id, job, index_id, out=out, logger=logger, generated_at=generated_at
                )
                html_after = _index_html(client, session_id, index_id)
                write_text(out / "superdocs" / "index.html", html_after)
                proof, cmap = _proof_html(html_after, index, files, diff_obj)
                cmap.index_document_id = index_id
                write_json(out / "superdocs" / "row_chunk_map.json", cmap)
                write_json(out / "proof.json", proof)

        if not live_ok(proof):
            state.stage = "failed_proof"
            write_json(state_path, state)
            raise ValidationError(
                "SuperDocs table does not equal canonical index.json (proof failed)",
                proof=proof,
            )

        state.stage = "ready_to_export"
        write_json(state_path, state)
        client.focus(session_id, index_id)
        export_pair(client, session_id, out / "export", logger)
        state.stage = "done"
        write_json(state_path, state)
    except ValidationError:
        raise
    except SuperDocsError as exc:
        from soc2_index.superdocs.client import AuthError

        state.stage = "failed"
        write_json(state_path, state)
        if isinstance(exc, AuthError):
            raise UsageError(str(exc), code=2) from exc
        raise SuperDocsRunError(str(exc)) from exc


def run(
    *,
    evidence: Path,
    out: Path,
    from_run: Path | None = None,
    catalog: Path | None = None,
    sample: bool = True,
    org: str = "Cedar Harbor Labs",
    period: str = "2025-01-01/2025-12-31",
    generated_at: str | None = None,
    session: str = "cedar-harbor-idx-v1",
    max_ops: int = 15,
    wait_timeout: int = 300,
    api_key: str | None = None,
) -> int:
    ts = clock_generated(generated_at)
    from_index = None
    if from_run is not None:
        idx_path = from_run / "index.json"
        if not idx_path.is_file():
            raise UsageError(f"--from has no index.json: {from_run}")
        from_index = IndexDoc.model_validate(load_json(idx_path))
        from_state_p = from_run / "state.json"
        if catalog is None and from_state_p.is_file():
            prev = load_json(from_state_p)
            cid = prev.get("catalog_id")
            if cid == "tsc-cc6-cc7":
                catalog = sample_catalog_path()
                sample = True
            elif cid == "tsc-cc":
                catalog = default_catalog_path()
                sample = False
        if session == "cedar-harbor-idx-v1" and from_state_p.is_file():
            sid = load_json(from_state_p).get("session_id")
            if sid:
                session = sid

    index, files, diff_obj, mapping = materialize(
        evidence,
        catalog,
        sample=sample,
        org=org,
        period=period,
        generated_at=ts,
        from_index=from_index,
        from_run=str(from_run) if from_run else None,
        to_run=str(out),
    )

    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "state.json"
    cat = load_catalog(catalog or (sample_catalog_path() if sample else default_catalog_path()))
    if not state_path.exists():
        state = RunState(
            stage="map",
            catalog_id=cat.id,
            catalog_sha256=cat.sha256,
            org=org,
            period=period,
            generated_at=ts,
            session_id=session,
            max_ops=max_ops,
            evidence_root=str(evidence.resolve()),
            from_run=str(from_run) if from_run else None,
        )
        create_state_excl(state_path, state)
    write_local_artifacts(out, index, files, mapping.ambiguous, diff_obj)
    proof = proof_local(index, files, evidence)
    write_json(out / "proof.json", proof)
    if proof.dangling:
        raise ValidationError("dangling Present rows", proof=proof)

    live_run(
        out=out,
        evidence=evidence,
        index=index,
        files=files,
        diff_obj=diff_obj,
        from_dir=from_run,
        session_id=session,
        max_ops=max_ops,
        wait_timeout=wait_timeout,
        generated_at=ts,
        api_key=api_key,
    )
    return 0
