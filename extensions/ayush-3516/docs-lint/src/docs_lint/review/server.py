"""The local review interface.

Deliberately built *after* the machine path and on top of it. The browser does not get its own
route into the applier: it posts the same decisions structure that `docs-lint apply` reads from a
file, so both doors open the same gate and the gate stays testable without a browser.

It binds to 127.0.0.1 on an ephemeral port with a single-use token in the URL. Findings can contain
whole paragraphs of somebody's unpublished documentation, and that is not something to serve on
every interface on the machine.
"""

from __future__ import annotations

import contextlib
import secrets
import threading
import webbrowser
from dataclasses import dataclass, field
from typing import Any

from ..model import Decision, Decisions, RunSummary, Source


@dataclass
class ReviewOutcome:
    """What the reviewer decided, once the page has been submitted."""

    decisions: Decisions | None = None
    cancelled: bool = False
    done: threading.Event = field(default_factory=threading.Event)


def findings_payload(summary: RunSummary) -> list[dict[str, Any]]:
    """The review queue: only fixable findings, since the rest have nothing to decide."""
    files: list[dict[str, Any]] = []
    for result in summary.results:
        fixable = [f for f in result.findings if f.is_fixable]
        if not fixable:
            continue
        files.append(
            {
                "path": result.path,
                "findings": [
                    {
                        "id": finding.finding_id,
                        "rule": finding.rule_id,
                        "severity": finding.severity.value,
                        "source": "ai" if finding.source is Source.SUPERDOCS else "rule",
                        "message": finding.message,
                        "explanation": finding.explanation,
                        "line": finding.anchor.start_line,
                        "section": finding.anchor.section,
                        "before": finding.original or "",
                        "after": finding.replacement or "",
                    }
                    for finding in sorted(fixable, key=lambda f: f.anchor.start_line)
                ],
            }
        )
    return files


def build_app(summary: RunSummary, outcome: ReviewOutcome, token: str):
    """A FastAPI app serving the review page and collecting one set of decisions."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="docs-lint review", docs_url=None, redoc_url=None)

    def check(supplied: str) -> None:
        # Constant-time compare: the token is the only thing standing between this page and any
        # other process on the machine.
        if not secrets.compare_digest(supplied, token):
            raise HTTPException(403, "bad or missing token")

    @app.get("/", response_class=HTMLResponse)
    async def index(token: str = ""):
        check(token)
        return HTMLResponse(PAGE)

    @app.get("/api/run")
    async def run(token: str = ""):
        check(token)
        return {
            "run_id": summary.run_id,
            "headline": f"{len([f for f in summary.all_findings if f.is_fixable])} "
            "proposed fix(es) awaiting your decision",
            "degraded": list(summary.degraded),
            "files": findings_payload(summary),
        }

    @app.post("/api/decisions")
    async def decide(body: dict[str, Any]):
        check(str(body.get("token", "")))
        items = body.get("decisions")
        if not isinstance(items, list):
            raise HTTPException(422, "decisions must be a list")

        outcome.decisions = Decisions(
            run_id=summary.run_id,
            decisions=tuple(
                Decision(
                    finding_id=str(item["finding_id"]), approved=bool(item.get("approved", False))
                )
                for item in items
                if isinstance(item, dict) and item.get("finding_id")
            ),
        )
        approved = len(outcome.decisions.approved_ids())
        outcome.done.set()
        return {"ok": True, "approved": approved, "rejected": len(items) - approved}

    @app.post("/api/cancel")
    async def cancel(body: dict[str, Any]):
        check(str(body.get("token", "")))
        outcome.cancelled = True
        outcome.done.set()
        return {"ok": True}

    return app


def run_review(
    summary: RunSummary,
    *,
    host: str = "127.0.0.1",
    open_browser: bool = True,
    timeout: float = 1800,
) -> ReviewOutcome:
    """Serve the review page, block until it is submitted, and return the decisions.

    Returns a cancelled outcome on timeout rather than an empty approval set, so an abandoned
    review can never be mistaken for "the reviewer approved nothing on purpose".
    """
    import uvicorn

    token = secrets.token_urlsafe(24)
    outcome = ReviewOutcome()
    config = uvicorn.Config(
        build_app(summary, outcome, token), host=host, port=0, log_level="error", access_log=False
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    try:
        if not _wait_for(lambda: server.started, timeout=20):
            raise RuntimeError("the review server did not start")
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://{host}:{port}/?token={token}"

        print(f"\n  Review the proposed fixes at:\n    {url}\n")
        print("  Nothing is applied until you submit. Ctrl-C cancels and changes nothing.\n")
        if open_browser:
            # A headless machine, or no browser configured, is not a failure: the URL is printed
            # above and the reviewer can open it themselves.
            with contextlib.suppress(Exception):
                webbrowser.open(url)

        if not outcome.done.wait(timeout=timeout):
            outcome.cancelled = True
            print("  Review timed out. Nothing was applied.")
    except KeyboardInterrupt:
        outcome.cancelled = True
        print("\n  Cancelled. Nothing was applied.")
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    return outcome


def _wait_for(predicate, *, timeout: float, interval: float = 0.02) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>docs-lint review</title>
<style>
  :root {
    --bg: #fbfaf8; --fg: #1c1b19; --muted: #6b6862; --line: #e2ded7;
    --card: #ffffff; --add: #1a7f37; --add-bg: #e8f5ec; --del: #b3261e; --del-bg: #fbeceb;
    --accent: #cf5c36; --ok: #1a7f37;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #16150f; --fg: #eeece6; --muted: #9c978d; --line: #322f28;
      --card: #1e1d16; --add: #4ac26b; --add-bg: #14261a; --del: #f4796b; --del-bg: #2a1614;
      --accent: #e8825c; --ok: #4ac26b;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  header {
    position: sticky; top: 0; z-index: 5; background: var(--bg);
    border-bottom: 1px solid var(--line); padding: 18px 24px;
    display: flex; gap: 16px; align-items: center; flex-wrap: wrap;
  }
  h1 { font-size: 17px; margin: 0; letter-spacing: -0.01em; }
  .count { color: var(--muted); font-size: 14px; }
  .spacer { flex: 1 1 auto; }
  main { padding: 24px; max-width: 900px; margin: 0 auto; }
  .file { margin-bottom: 28px; }
  .file h2 {
    font-size: 14px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    margin: 0 0 10px; color: var(--muted); font-weight: 600;
  }
  .card {
    background: var(--card); border: 1px solid var(--line); border-radius: 10px;
    padding: 14px 16px; margin-bottom: 10px;
  }
  .card.decided-yes { border-color: var(--ok); }
  .card.decided-no { opacity: .55; }
  .meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
  .tag {
    font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
    padding: 2px 7px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted);
  }
  .tag.error { color: var(--del); border-color: var(--del); }
  .tag.ai { color: var(--accent); border-color: var(--accent); }
  .loc { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); }
  .msg { margin: 0 0 10px; }
  .why { color: var(--muted); font-size: 13px; margin: -6px 0 10px; font-style: italic; }
  pre {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px;
    margin: 0; padding: 7px 10px; border-radius: 6px; white-space: pre-wrap;
    word-break: break-word; overflow-x: auto;
  }
  pre.before { background: var(--del-bg); color: var(--del); }
  pre.after { background: var(--add-bg); color: var(--add); margin-top: 4px; }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  button {
    font: inherit; padding: 6px 14px; border-radius: 7px; cursor: pointer;
    border: 1px solid var(--line); background: transparent; color: var(--fg);
  }
  button:hover { border-color: var(--fg); }
  button.on-yes { background: var(--ok); border-color: var(--ok); color: #fff; }
  button.on-no { background: var(--del); border-color: var(--del); color: #fff; }
  button.primary { background: var(--fg); color: var(--bg); border-color: var(--fg); font-weight: 600; }
  button.primary:disabled { opacity: .4; cursor: not-allowed; }
  .warn {
    background: var(--del-bg); color: var(--del); border: 1px solid var(--del);
    border-radius: 8px; padding: 10px 14px; margin-bottom: 20px; font-size: 14px;
  }
  .done { text-align: center; padding: 80px 24px; }
  .done h2 { font-size: 20px; }
</style>
</head>
<body>
<header>
  <h1>docs-lint review</h1>
  <span class="count" id="count"></span>
  <span class="spacer"></span>
  <button id="all-no">Reject all</button>
  <button id="all-yes">Approve all</button>
  <button class="primary" id="submit" disabled>Apply approved</button>
</header>
<main id="main">Loading…</main>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
const decisions = new Map();
let files = [];

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
}

function render() {
  const main = document.getElementById("main");
  main.innerHTML = files.map(file => `
    <section class="file">
      <h2>${esc(file.path)}</h2>
      ${file.findings.map(f => `
        <article class="card" id="card-${f.id}">
          <div class="meta">
            <span class="tag ${f.severity === "error" ? "error" : ""}">${esc(f.severity)}</span>
            <span class="tag ${f.source === "ai" ? "ai" : ""}">${f.source === "ai" ? "style guide review" : "rule"}</span>
            <span class="loc">${esc(f.rule)} · line ${f.line}</span>
          </div>
          <p class="msg">${esc(f.message)}</p>
          ${f.explanation ? `<p class="why">${esc(f.explanation)}</p>` : ""}
          <pre class="before">${esc(f.before)}</pre>
          <pre class="after">${esc(f.after)}</pre>
          <div class="actions">
            <button data-id="${f.id}" data-v="1">Approve</button>
            <button data-id="${f.id}" data-v="0">Reject</button>
          </div>
        </article>`).join("")}
    </section>`).join("");

  main.querySelectorAll("button[data-id]").forEach(b => {
    b.onclick = () => { decisions.set(b.dataset.id, b.dataset.v === "1"); paint(); };
  });
  paint();
}

function paint() {
  let total = 0, approved = 0;
  files.forEach(file => file.findings.forEach(f => {
    total++;
    const card = document.getElementById("card-" + f.id);
    const choice = decisions.get(f.id);
    card.className = "card" + (choice === true ? " decided-yes" : choice === false ? " decided-no" : "");
    card.querySelectorAll("button[data-id]").forEach(b => {
      const yes = b.dataset.v === "1";
      b.className = choice === undefined ? "" : (yes === choice ? (yes ? "on-yes" : "on-no") : "");
    });
    if (choice === true) approved++;
  }));
  document.getElementById("count").textContent =
    `${decisions.size} of ${total} decided · ${approved} to apply`;
  document.getElementById("submit").disabled = decisions.size === 0;
}

document.getElementById("all-yes").onclick = () => {
  files.forEach(f => f.findings.forEach(x => decisions.set(x.id, true))); paint();
};
document.getElementById("all-no").onclick = () => {
  files.forEach(f => f.findings.forEach(x => decisions.set(x.id, false))); paint();
};

document.getElementById("submit").onclick = async () => {
  const payload = [];
  files.forEach(f => f.findings.forEach(x =>
    payload.push({ finding_id: x.id, approved: decisions.get(x.id) === true })));
  const res = await fetch("/api/decisions", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, decisions: payload })
  });
  const out = await res.json();
  document.body.innerHTML =
    `<div class="done"><h2>${out.approved} approved, ${out.rejected} rejected</h2>
     <p>Applying now — you can close this tab and return to the terminal.</p></div>`;
};

fetch("/api/run?token=" + encodeURIComponent(token))
  .then(r => r.ok ? r.json() : Promise.reject(r.status))
  .then(data => {
    files = data.files;
    if (data.degraded && data.degraded.length) {
      document.getElementById("main").insertAdjacentHTML("beforebegin",
        `<div class="warn">This run was degraded: ${data.degraded.map(esc).join("; ")}</div>`);
    }
    render();
  })
  .catch(() => {
    document.getElementById("main").textContent =
      "Could not load the run. The link may have expired — re-run docs-lint fix.";
  });
</script>
</body>
</html>
"""
