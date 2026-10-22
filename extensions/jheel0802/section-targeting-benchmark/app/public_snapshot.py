from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .db import Database, now


SCHEMA_VERSION = 1
PRIVATE_KEYS = {
    "api_key", "authorization", "token", "access_token", "refresh_token",
    "user_id", "session_id", "job_id", "document_id", "durable_document_id",
    "session_document_id", "account_id", "organization_id", "team_id", "email",
}
REVIEW_IDENTIFIERS = {"external_case_id", "chunk_id", "change_id", "insert_after_chunk_id", "insert_before_chunk_id"}


def sanitize(value: Any) -> Any:
    """Remove remote/account identifiers while retaining reviewable benchmark evidence."""
    if isinstance(value, dict):
        cleaned={}
        for key,item in value.items():
            lowered=key.lower()
            if lowered in PRIVATE_KEYS or (lowered.endswith("_id") and lowered not in REVIEW_IDENTIFIERS):
                continue
            if lowered=="usage":
                item={k:item.get(k) for k in ("was_billable","ops_charged") if k in item} if isinstance(item,dict) else None
            if lowered in {"promotions","monthly_used","monthly_limit","monthly_remaining","subscription_tier","bucket_used"}:
                continue
            cleaned[key]=sanitize(item)
        return cleaned
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def _clean_json(raw: str | None) -> str | None:
    if not raw:
        return raw
    return json.dumps(sanitize(json.loads(raw)), separators=(",", ":"))


def export_public_snapshot(db: Database, destination: str | Path, benchmark_run_id: int | None = None) -> dict[str, Any]:
    selected = db.one("SELECT * FROM benchmark_runs WHERE id=?", (benchmark_run_id,)) if benchmark_run_id else db.one("SELECT * FROM benchmark_runs WHERE selected=1")
    if not selected:
        raise ValueError("benchmark run not found")
    latest = db.all("""WITH latest AS (
      SELECT case_id,MAX(id) id FROM runs WHERE benchmark_run_id=? GROUP BY case_id
    ) SELECT r.*,c.external_case_id,f.name failure_category
      FROM runs r JOIN cases c ON c.id=r.case_id
      LEFT JOIN failure_categories f ON f.id=r.failure_category_id
      WHERE r.benchmark_run_id=? AND c.external_case_id IS NOT NULL AND
        (r.id IN (SELECT id FROM latest) OR EXISTS(SELECT 1 FROM applied_verifications a WHERE a.run_id=r.id)
         OR EXISTS(SELECT 1 FROM guided_recoveries g WHERE g.original_run_id=r.id))
      ORDER BY r.id""", (selected["id"],selected["id"]))
    attempts=[]
    for row in latest:
        run_id=row.pop("id"); row.pop("case_id",None); row.pop("benchmark_run_id",None)
        row.pop("failure_category_id",None); row["session_id"]=None; row["job_id"]=None
        row["evidence_json"]=_clean_json(row.get("evidence_json"))
        row["raw_response_json"]=_clean_json(row.get("raw_response_json"))
        applied=db.one("SELECT * FROM applied_verifications WHERE run_id=?",(run_id,))
        if applied:
            for key in ("id","run_id","session_document_id"): applied.pop(key,None)
            for key in ("pending_changes_json","post_job_json"):
                applied[key]=_clean_json(applied.get(key))
        recovery=db.one("SELECT * FROM guided_recoveries WHERE original_run_id=?",(run_id,))
        if recovery:
            for key in ("id","original_run_id","recovery_session_id","recovery_job_id"): recovery.pop(key,None)
            for key in ("original_pending_changes_json","rejection_response_json","recovery_pending_changes_json","recovery_raw_response_json"):
                recovery[key]=_clean_json(recovery.get(key))
        attempts.append({"run":sanitize(row),"applied_verification":sanitize(applied),"guided_recovery":sanitize(recovery)})
    payload={
        "schema_version":SCHEMA_VERSION,
        "snapshot_key":f"published-run-{selected['id']}-corpus-{selected.get('corpus_version') or 'unknown'}",
        "name":f"Published {selected['name']}",
        "corpus_version":selected.get("corpus_version"),
        "corpus_case_total":selected.get("corpus_case_total"),
        "created_at":selected.get("created_at"),
        "attempts":attempts,
    }
    destination=Path(destination); destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(payload,indent=2,ensure_ascii=False)+"\n")
    return {"snapshot_key":payload["snapshot_key"],"attempts":len(attempts),"path":str(destination)}


def import_public_snapshot(db: Database, source: str | Path) -> dict[str, Any]:
    path=Path(source); payload=json.loads(path.read_text())
    if payload.get("schema_version")!=SCHEMA_VERSION: raise ValueError("unsupported public snapshot schema")
    if db.one("SELECT id FROM benchmark_runs WHERE snapshot_key=?",(payload["snapshot_key"],)):
        run=db.one("SELECT * FROM benchmark_runs WHERE snapshot_key=?",(payload["snapshot_key"],))
        return {"status":"already_imported","benchmark_run_id":run["id"],"attempts":len(payload["attempts"])}
    expected=int(payload["corpus_case_total"])
    represented={x["run"]["external_case_id"] for x in payload["attempts"]}
    if len(represented)!=expected: raise ValueError("public snapshot does not contain a final attempt for every official case")
    with db.connect() as conn:
        case_rows=conn.execute("SELECT id,external_case_id FROM cases WHERE external_case_id IS NOT NULL").fetchall()
        case_ids={r["external_case_id"]:r["id"] for r in case_rows}
        missing=[x["run"]["external_case_id"] for x in payload["attempts"] if x["run"]["external_case_id"] not in case_ids]
        if missing: raise ValueError(f"snapshot cases are not imported: {', '.join(missing)}")
        # Remove only the automatically-created, untouched placeholder in a
        # brand-new database. Never remove a user's real run history.
        existing_runs=conn.execute("SELECT id,read_only,snapshot_key FROM benchmark_runs").fetchall()
        if len(existing_runs)==1:
            placeholder=existing_runs[0]
            executions=conn.execute("SELECT COUNT(*) FROM runs WHERE benchmark_run_id=?",(placeholder["id"],)).fetchone()[0]
            if not executions and not placeholder["read_only"] and not placeholder["snapshot_key"]:
                conn.execute("DELETE FROM benchmark_runs WHERE id=?",(placeholder["id"],))
        conn.execute("UPDATE benchmark_runs SET selected=0")
        benchmark_run_id=conn.execute("""INSERT INTO benchmark_runs(name,selected,corpus_version,corpus_case_total,read_only,snapshot_key,created_at)
          VALUES (?,?,?,?,?,?,?)""",(payload["name"],1,payload.get("corpus_version"),expected,1,payload["snapshot_key"],payload.get("created_at") or now())).lastrowid
        conn.executemany("INSERT INTO benchmark_run_cases(benchmark_run_id,case_id) VALUES (?,?)",[(benchmark_run_id,cid) for cid in case_ids.values()])
        for item in payload["attempts"]:
            run=dict(item["run"]); external=run.pop("external_case_id"); category=run.pop("failure_category",None)
            category_id=None
            if category:
                found=conn.execute("SELECT id FROM failure_categories WHERE name=?",(category,)).fetchone()
                if not found:
                    conn.execute("INSERT INTO failure_categories(name,active) VALUES (?,0)",(category,)); found=conn.execute("SELECT id FROM failure_categories WHERE name=?",(category,)).fetchone()
                category_id=found["id"]
            columns=["case_id","benchmark_run_id","failure_category_id"]+list(run)
            values=[case_ids[external],benchmark_run_id,category_id]+list(run.values())
            run_id=conn.execute(f"INSERT INTO runs({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",values).lastrowid
            for table,key,fk in (("applied_verifications","applied_verification","run_id"),("guided_recoveries","guided_recovery","original_run_id")):
                record=item.get(key)
                if record:
                    record=dict(record); columns=[fk]+list(record); values=[run_id]+list(record.values())
                    conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",values)
    return {"status":"imported","benchmark_run_id":benchmark_run_id,"attempts":len(payload["attempts"])}
