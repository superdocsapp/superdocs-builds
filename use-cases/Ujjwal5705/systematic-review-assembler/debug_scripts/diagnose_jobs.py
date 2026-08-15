from superdocs_client import get_session_jobs, get_job

jobs = get_session_jobs("review-package-full-assembly-v2")
job_ids = [j if isinstance(j, str) else j.get("job_id") for j in jobs]
print(f"Total jobs: {len(job_ids)}")
print()

for jid in job_ids:
    job = get_job(jid)
    status = job.get("status")
    created = job.get("created_at", "?")
    result = job.get("result") or {}
    summary = result.get("changes_summary", "")
    error = job.get("error")
    print(
        f"{created} | {jid[:8]} | status={status} | summary={summary!r} | error={error}"
    )
