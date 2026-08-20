const form = document.getElementById("tailor-form");
const statusEl = document.getElementById("status");
const submitBtn = document.getElementById("submit-btn");
const revisionsList = document.getElementById("revisions-list");
const emptyState = document.getElementById("empty-state");
const editorEl = document.getElementById("editor");
const downloadBtn = document.getElementById("download-btn");

let currentBlobUrl = null;
let superdoc = null;
let revisionState = [];

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  submitBtn.disabled = true;
  submitBtn.textContent = "Tailoring…";
  statusEl.textContent = "Reading your resume and matching it to the role…";
  revisionsList.hidden = true;
  revisionsList.innerHTML = "";

  try {
    const formData = new FormData(form);
    const res = await fetch("/api/tailor", { method: "POST", body: formData });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || "Something went wrong.");
    }

    const bytes = Uint8Array.from(atob(data.docx), (c) => c.charCodeAt(0));
    const blob = new Blob([bytes], {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });

    if (currentBlobUrl) URL.revokeObjectURL(currentBlobUrl);
    currentBlobUrl = URL.createObjectURL(blob);

    emptyState.hidden = true;
    editorEl.hidden = false;
    editorEl.innerHTML = "";

    // eslint-disable-next-line no-undef -- SuperDoc is loaded as a global via the jsdelivr script tag
    superdoc = new SuperDoc({
      selector: "#editor",
      documentMode: "editing",
      // We own the review UI in the side panel. `ui: false` disables every
      // built-in control, dialog, and popover — including the in-document
      // accept/reject controls, which render at the document's font sizes
      // (huge next to panel buttons). The tracked-change redline itself is
      // document rendering, so it stays visible.
      ui: false,
      // Permission gate for tracked-change affordances: deny every
      // trackedChanges.* permission so the layout engine stops painting the
      // in-document Accept/Reject buttons entirely. Accept/Reject stays
      // available programmatically through doc.trackChanges.decide(), which
      // is the same kernel call the runtime's own accept path uses — the
      // resolver only shapes what UI chrome is shown, not the Document API.
      permissionResolver: ({ permission }) =>
        permission.startsWith("trackedChanges.") ? false : undefined,
      documents: [{ id: "tailored-resume", type: "docx", data: blob }],
    });

    superdoc.on("ready", () => wireTrackedChanges(data.revisions ?? []));
    superdoc.on("exception", (payload) => {
      console.error("superdoc exception:", payload);
    });

    downloadBtn.hidden = false;
    downloadBtn.onclick = downloadCurrent;

    statusEl.textContent =
      "Done — review each change in the list, then accept or reject it.";
  } catch (err) {
    console.error(err);
    statusEl.textContent = err.message || "Tailoring failed.";
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Tailor resume";
  }
});

// Match the server's revision list to the live tracked changes inside the
// editor (by block id), so Accept/Reject can address real change ids.
async function wireTrackedChanges(serverRevisions) {
  revisionState = serverRevisions.map((r) => ({
    ...r,
    changeIds: [],
    decision: null,
  }));

  if (!revisionState.length) {
    statusEl.textContent =
      "Done — the model proposed no changes. Try a more detailed job description.";
    return;
  }

  try {
    const doc = superdoc?.activeEditor?.doc;
    const result = doc ? await doc.trackChanges.list({ limit: 500 }) : null;
    const items = result?.items ?? result ?? [];

    const byBlock = new Map();
    for (const change of items) {
      const blockId = change.navigationTarget?.blockId;
      if (!blockId) continue;
      if (!byBlock.has(blockId)) byBlock.set(blockId, []);
      byBlock.get(blockId).push(change.id);
    }
    for (const rev of revisionState) {
      rev.changeIds = byBlock.get(rev.nodeId) ?? [];
    }
  } catch (err) {
    console.error("tracked-changes lookup failed:", err);
    statusEl.textContent =
      "Warning: could not read tracked changes from the editor — Accept/Reject may not work.";
  }

  renderRevisions();
}

function renderRevisions() {
  revisionsList.hidden = false;
  revisionsList.innerHTML = revisionState
    .map((rev, i) => {
      const resolved = rev.decision === "accept" || rev.decision === "reject";
      const decisionLabel =
        rev.decision === "accept"
          ? "Accepted"
          : rev.decision === "reject"
            ? "Rejected"
            : "";
      const note = rev.lengthFlag
        ? " — length changed a lot, double-check layout"
        : "";

      return `<li class="revision${resolved ? " is-resolved" : ""}" data-idx="${i}">
        <div class="revision-head">
          <span class="revision-meta">Line ${rev.line} · Page ${rev.page}</span>
          ${
            resolved
              ? `<span class="revision-decision${rev.decision === "reject" ? " is-rejected" : ""}">${decisionLabel}</span>`
              : `<span class="revision-actions">
                  <button type="button" class="btn btn-accept" data-action="accept">✓ Accept</button>
                  <button type="button" class="btn btn-reject" data-action="reject">✗ Reject</button>
                </span>`
          }
          <button type="button" class="btn btn-locate" data-action="locate">Locate</button>
        </div>
        <div class="revision-diff">
          <div class="revision-old">${escapeHtml(rev.original)}</div>
          <div class="revision-new">${escapeHtml(rev.revisedText)}</div>
        </div>
        <div class="revision-reason${rev.lengthFlag ? " flagged" : ""}">${escapeHtml(rev.reason)}${note}</div>
      </li>`;
    })
    .join("");
}

revisionsList.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-action]");
  if (!btn) return;
  const li = btn.closest("li.revision");
  const rev = revisionState[Number(li?.dataset.idx)];
  if (!rev) return;

  const action = btn.dataset.action;

  if (action === "locate") {
    try {
      await superdoc?.scrollToElement(rev.nodeId);
    } catch (err) {
      console.error("locate failed:", err);
    }
    return;
  }

  if (rev.decision) return; // already resolved

  btn.disabled = true;
  try {
    const doc = superdoc?.activeEditor?.doc;
    if (!doc) throw new Error("Editor is not ready yet.");
    const decision = action === "accept" ? "accept" : "reject";
    for (const id of rev.changeIds) {
      await doc.trackChanges.decide({
        decision,
        target: { kind: "id", id },
      });
    }
    rev.decision = decision;
    statusEl.textContent = `Change on line ${rev.line} ${decision === "accept" ? "accepted" : "rejected"}.`;
  } catch (err) {
    console.error("decide failed:", err);
    statusEl.textContent =
      `Could not ${action} the change on line ${rev.line} — ${err.message || "check console"}.`;
  }
  renderRevisions();
});

async function downloadCurrent() {
  downloadBtn.disabled = true;
  try {
    let blob = currentBlobUrl
      ? await fetch(currentBlobUrl).then((r) => r.blob())
      : null;

    // Export the live editor state so accept/reject decisions are baked in;
    // fall back to the original tailored file if the export API is missing.
    try {
      if (superdoc?.export) {
        const exported = await superdoc.export({ exportType: "docx" });
        if (exported) blob = exported;
      }
    } catch (err) {
      console.warn("live export failed, falling back to the original file", err);
    }

    if (!blob) throw new Error("No document to download.");
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "tailored-resume.docx";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (err) {
    console.error(err);
    statusEl.textContent = `Download failed — ${err.message || "check console"}.`;
  } finally {
    downloadBtn.disabled = false;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}