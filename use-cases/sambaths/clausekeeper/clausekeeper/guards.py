RECHECK_ROLES = ("manual", "procedure")


def role_allows(doc: dict) -> bool:
    return doc.get("role") in RECHECK_ROLES


def is_echo(event: dict, conn) -> bool:
    job_id = event.get("job_id")
    if not job_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM our_jobs WHERE job_id = ?", (job_id,)).fetchone()
    return row is not None


def already_run(conn, run_key: str) -> bool:
    row = conn.execute(
        "SELECT status FROM runs WHERE run_key = ? AND status = 'done'",
        (run_key,)).fetchone()
    return row is not None


def mark_run(conn, run_key: str, kind: str, ops_charged: int = 0,
             status: str = "done"):
    from . import db
    conn.execute(
        "INSERT INTO runs(run_key, kind, started_at, completed_at, "
        "ops_charged, status) VALUES(?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(run_key) DO UPDATE SET completed_at = excluded.completed_at,"
        " ops_charged = excluded.ops_charged, status = excluded.status",
        (run_key, kind, db.now(), db.now(), ops_charged, status))
    conn.commit()
