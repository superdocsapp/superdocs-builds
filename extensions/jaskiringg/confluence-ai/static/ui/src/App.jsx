import { useEffect, useMemo, useState } from "react";
import { call } from "./api.js";

function diffPreview(oldHtml, newHtml) {
  return { oldHtml: oldHtml || "", newHtml: newHtml || "" };
}

export default function App() {
  const [ctx, setCtx] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [section, setSection] = useState(null);
  const [message, setMessage] = useState("Change the freeze window to 01:00-05:00 IST. Do not invent other policy.");
  const [job, setJob] = useState(null);
  const [pending, setPending] = useState([]);
  const [decisions, setDecisions] = useState({});
  const [role, setRole] = useState("author");
  const [approver, setApprover] = useState(null);
  const [users, setUsers] = useState([]);
  const [queue, setQueue] = useState([]);
  const [tab, setTab] = useState("edit");
  const [note, setNote] = useState("");

  const pageId = ctx?.page?.id || "demo-page";
  const spaceId = ctx?.page?.spaceId || "demo-space";

  async function refresh(nextPageId) {
    const data = await call("getContext", {
      pageId: nextPageId || (ctx?.page?.id && !String(ctx.page.id).startsWith("demo") ? ctx.page.id : undefined),
      spaceId: ctx?.page?.spaceId && !String(ctx.page.spaceId).startsWith("demo") ? ctx.page.spaceId : undefined,
    });
    setCtx(data);
    if (!section && data.sections?.[0]) setSection(data.sections[0]);
    return data;
  }

  useEffect(() => {
    (async () => {
      try {
        const data = await refresh();
        const listed = await call("listPages", { spaceId: data.page?.spaceId });
        setQueue(listed.pages || []);
        const found = await call("findUsers", { query: "" });
        setUsers(found.users || []);
      } catch (e) {
        setErr(e.message);
      }
    })();
  }, []);

  async function pollUntilSettled(jobId, sessionId) {
    for (let i = 0; i < 40; i += 1) {
      const p = await call("pollJob", { jobId, sessionId });
      if (p.status === "awaiting_approval" && p.awaitingKind === "continue_prompt") {
        await call("resumeLargeEdit", { jobId, sessionId, continue: true });
        await new Promise((r) => setTimeout(r, 2000));
        continue;
      }
      if (p.status === "awaiting_approval") {
        const changes = p.pendingChanges || [];
        setPending(changes);
        const next = {};
        for (const c of changes) next[c.change_id] = true;
        setDecisions(next);
        return p;
      }
      if (p.status === "completed" || p.status === "failed") return p;
      await new Promise((r) => setTimeout(r, 2000));
    }
    throw new Error("Timed out waiting for SuperDocs. Large edits can take a few minutes — try again.");
  }

  async function runEdit(opts = {}) {
    setErr("");
    setNote("");
    setBusy(true);
    try {
      const payload = {
        pageId,
        message,
        house: !!opts.house,
        role,
        modelTier: "core",
      };
      if (section && !opts.wholePage && !opts.house) {
        payload.start = section.start;
        payload.end = section.end;
      }
      const started = await call("startEdit", payload);
      setJob(started);
      const settled = await pollUntilSettled(started.jobId, started.sessionId);
      if (settled.status === "failed") throw new Error(settled.error || "Job failed");
      setNote(settled.status === "completed" && !settled.pendingChanges?.length
        ? "Job finished with no pending diffs."
        : `${(settled.pendingChanges || pending).length || "Pending"} change(s) to review.`);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitDecisions() {
    if (!job) return;
    setBusy(true);
    setErr("");
    try {
      const list = pending.map((c) => ({
        change_id: c.change_id,
        chunk_id: c.chunk_id,
        operation: c.operation,
        new_html: c.new_html,
        old_html: c.old_html,
        insert_after_chunk_id: c.insert_after_chunk_id,
        approved: decisions[c.change_id] !== false,
      }));
      await call("decide", { sessionId: job.sessionId, jobId: job.jobId, decisions: list });
      if (approver && role === "author") {
        await call("sendToApprover", {
          pageId,
          approverAccountId: approver.accountId,
          approverName: approver.displayName,
          sessionId: job.sessionId,
          jobId: job.jobId,
        });
        setNote(`Sent to ${approver.displayName}. Write-back is blocked until they accept.`);
        await refresh();
        return;
      }
      const written = await call("writeBack", {
        sessionId: job.sessionId,
        pageId,
        decisions: list,
        role,
        actorAccountId: role === "approver" ? approver?.accountId : "demo-author",
      });
      setNote(`Wrote accepted ranges only. Confluence version ${written.version}${written.demo ? " (demo page)" : ""}.`);
      setPending([]);
      await refresh();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadPdf() {
    setBusy(true);
    setErr("");
    try {
      const pdf = await call("exportBrandedPdf", { pageId, sessionId: job?.sessionId });
      const bin = atob(pdf.base64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: pdf.contentType });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = pdf.filename;
      a.click();
      setNote(`Exported ${pdf.filename} (${pdf.bytes} bytes).`);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  const blocked = ctx?.review?.status === "awaiting_approver";

  const queueView = useMemo(
    () => queue.map((p) => ({ ...p, current: p.id === pageId })),
    [queue, pageId]
  );

  if (!ctx) {
    return <div className="shell"><p>{err || "Loading page…"}</p></div>;
  }

  return (
    <div className="shell">
      <header className="top">
        <div>
          <div className="kicker">
            {ctx.page.demo ? "Sidecar demo page" : "Live Confluence page"}
          </div>
          <h1>{ctx.page.title}</h1>
          <p className="meta">
            v{ctx.page.version}
            {ctx.page.demo ? " · not writing to Confluence yet" : " · writes back to the wiki page"}
            {" · "}
            review: {ctx.review?.status || "draft"}
            {!ctx.hasSuperDocsKey ? " · missing SUPERDOCS_API_KEY" : ""}
          </p>
        </div>
        <div className="tabs">
          <button className={tab === "edit" ? "on" : ""} onClick={() => setTab("edit")}>Page edit</button>
          <button className={tab === "space" ? "on" : ""} onClick={() => setTab("space")}>Space queue</button>
        </div>
      </header>

      {err ? <div className="banner bad">{err}</div> : null}
      {note ? <div className="banner">{note}</div> : null}
      {blocked ? (
        <div className="banner warn">
          Publish / write-back blocked until {ctx.review.approverName || "named approver"} accepts.
          Switch role to Approver to finish.
        </div>
      ) : null}

      {tab === "space" ? (
        <section className="panel">
          <h2>Normalise space — page by page</h2>
          <p className="hint">
            House structure is applied one page at a time. Nothing is bulk-overwritten.
            Open a page, review diffs, then move to the next.
          </p>
          <ul className="queue">
            {queueView.map((p) => (
              <li key={p.id} className={p.current ? "current" : ""}>
                <button
                  onClick={() => {
                    refresh(p.id)
                      .then((data) => {
                        setSection(data.sections?.[0] || null);
                        setTab("edit");
                      })
                      .catch((e) => setErr(e.message));
                  }}
                >
                  {p.title}
                </button>
              </li>
            ))}
          </ul>
          <button disabled={busy} onClick={() => runEdit({ house: true, wholePage: true })}>
            {busy ? "Working…" : "Propose house structure for this page"}
          </button>
        </section>
      ) : (
        <div className="grid">
          <section className="panel">
            <h2>Section</h2>
            <ul className="sections">
              {(ctx.sections || []).map((s) => (
                <li key={`${s.start}-${s.heading}`}>
                  <button
                    className={section?.start === s.start ? "on" : ""}
                    onClick={() => setSection(s)}
                  >
                    <span className={`lvl l${s.level}`}>{s.heading}</span>
                    {s.opaqueCount ? <em>{s.opaqueCount} preserved</em> : null}
                  </button>
                </li>
              ))}
            </ul>
            <label>
              Instruction
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={4} />
            </label>
            <div className="row">
              <button disabled={busy || !ctx.hasSuperDocsKey} onClick={() => runEdit({})}>
                {busy ? "SuperDocs working…" : "Propose edit for section"}
              </button>
              <button disabled={busy} className="ghost" onClick={() => runEdit({ wholePage: true })}>
                Whole page
              </button>
            </div>
          </section>

          <section className="panel">
            <h2>Review</h2>
            <div className="row wrap">
              <label className="inline">
                Role
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="author">Author</option>
                  <option value="approver">Approver</option>
                </select>
              </label>
              <label className="inline">
                Named approver
                <select
                  value={approver?.accountId || ""}
                  onChange={(e) => setApprover(users.find((u) => u.accountId === e.target.value) || null)}
                >
                  <option value="">None — author can write back</option>
                  {users.map((u) => (
                    <option key={u.accountId} value={u.accountId}>{u.displayName}</option>
                  ))}
                </select>
              </label>
            </div>

            {!pending.length ? (
              <p className="hint">No pending diffs. Select a section and send an instruction.</p>
            ) : (
              pending.map((c) => {
                const d = diffPreview(c.old_html, c.new_html);
                const accepted = decisions[c.change_id] !== false;
                return (
                  <article key={c.change_id} className={`change ${accepted ? "ok" : "no"}`}>
                    <header>
                      <strong>{c.operation || "edit"}</strong>
                      <span>{c.ai_explanation || ""}</span>
                    </header>
                    <div className="diff">
                      <div className="old" dangerouslySetInnerHTML={{ __html: d.oldHtml || "<em>create</em>" }} />
                      <div className="new" dangerouslySetInnerHTML={{ __html: d.newHtml || "<em>delete</em>" }} />
                    </div>
                    <div className="row">
                      <button className={accepted ? "on" : "ghost"} onClick={() => setDecisions((x) => ({ ...x, [c.change_id]: true }))}>Accept</button>
                      <button className={!accepted ? "on" : "ghost"} onClick={() => setDecisions((x) => ({ ...x, [c.change_id]: false }))}>Reject</button>
                    </div>
                  </article>
                );
              })
            )}

            <div className="row">
              <button disabled={busy || !pending.length} onClick={submitDecisions}>
                {approver && role === "author" ? "Send to approver" : "Write accepted ranges back"}
              </button>
              <button disabled={busy} className="ghost" onClick={downloadPdf}>Export branded PDF</button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
