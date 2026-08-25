const API_BASE = "http://127.0.0.1:8000";

let state = {
  matterId: null,
  documentId: null,
  userId: null,
  jobId: null,
  pendingChanges: [],
};

Office.onReady(() => {
  document.getElementById("checkoutBtn").onclick = handleCheckout;
  document.getElementById("proposeBtn").onclick = handleProposeEdit;
  document.getElementById("checkinBtn").onclick = handleCheckin;
});

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-User-Id": state.userId,
      ...(options.headers || {}),
    },
  });
  const body = await response.json();
  if (!response.ok) {
    const isStructured = body.detail && typeof body.detail === "object";
    const message = isStructured ? body.detail.message : body.detail;
    const err = new Error(message || "Request failed");
    // Some errors (e.g. checkin refusing over unresolved changes) carry
    // structured detail beyond a message - attach it so a caller can react
    // (re-render the changes still needing a decision) instead of just
    // displaying text.
    if (isStructured) err.detail = body.detail;
    throw err;
  }
  return body;
}

function setStatus(text) {
  document.getElementById("statusLine").textContent = text;
}

async function handleCheckout() {
  state.matterId = document.getElementById("matterIdInput").value.trim();
  state.documentId = document.getElementById("documentIdInput").value.trim();
  state.userId = document.getElementById("userIdInput").value.trim();

  try {
    setStatus("Checking out...");
    const result = await api(
      `/matters/${state.matterId}/documents/${state.documentId}/checkout`,
      { method: "POST" }
    );
    setStatus(`Checked out - version ${result.version_loaded} loaded.`);
    document.getElementById("edit-section").style.display = "block";
    document.getElementById("checkin-section").style.display = "block";
    await loadVersionHistory();
  } catch (err) {
    setStatus(`Checkout failed: ${err.message}`);
  }
}

async function handleProposeEdit() {
  const instruction = document.getElementById("instructionInput").value.trim();
  if (!instruction) return;

  try {
    setStatus("Asking SuperDocs to propose an edit... this can take a while on larger documents - that's normal, not a crash.");
    const result = await api(
      `/matters/${state.matterId}/documents/${state.documentId}/edit`,
      { method: "POST", body: JSON.stringify({ instruction }) }
    );
    state.jobId = result.job_id;
    state.pendingChanges = result.pending_changes;

    if (result.pending_changes.length === 0) {
      setStatus("No changes proposed - the AI may not have understood the instruction, or the content already exists.");
    } else {
      setStatus(`${result.pending_changes.length} change(s) proposed - review below.`);
    }
    renderPendingChanges();
  } catch (err) {
    setStatus(`Edit request failed: ${err.message}`);
  }
}

function renderPendingChanges() {
  const container = document.getElementById("changesList");
  container.innerHTML = "";

  state.pendingChanges.forEach((change) => {
    const card = document.createElement("div");
    card.className = "change-card";
    card.innerHTML = `
      <div class="explanation">${change.ai_explanation || "(no explanation provided)"}</div>
      <div class="html-preview">${escapeHtml(change.new_html || "")}</div>
      <div class="actions">
        <button class="accept-btn">Accept</button>
        <button class="deny-btn">Deny</button>
      </div>
    `;
    card.querySelector(".accept-btn").onclick = () => handleDecision(change, true);
    card.querySelector(".deny-btn").onclick = () => handleDecision(change, false);
    container.appendChild(card);
  });
}

function escapeHtml(html) {
  const div = document.createElement("div");
  div.textContent = html;
  return div.innerHTML;
}

async function handleDecision(change, approved) {
  try {
    setStatus(approved ? "Applying approved change..." : "Discarding rejected change...");

    const result = await api(
      `/matters/${state.matterId}/documents/${state.documentId}/review`,
      {
        method: "POST",
        body: JSON.stringify({
          job_id: state.jobId,
          decisions: [{ change_id: change.change_id, approved }],
        }),
      }
    );

    if (approved) {
      await insertApprovedChange(change);
    }

    // Trust the server's remaining_pending_changes as the new full list,
    // rather than just filtering out the one just decided. SuperDocs can
    // surface a change that was never part of the original edit response -
    // filtering locally silently drops it, and nothing then stops check-in
    // from proceeding as if review were complete.
    state.pendingChanges = result.remaining_pending_changes || [];
    renderPendingChanges();
    setStatus(
      state.pendingChanges.length > 0
        ? `${state.pendingChanges.length} more change(s) to review - SuperDocs proposed additional edits.`
        : approved
        ? "Change applied to the document."
        : "Change discarded - document untouched."
    );
  } catch (err) {
    setStatus(`Failed to process decision: ${err.message}`);
  }
}

async function insertApprovedChange(change) {
  await Word.run(async (context) => {
    if (change.operation === "create" || !change.old_html) {
      context.document.body.insertHtml(change.new_html, Word.InsertLocation.end);
      await context.sync();
      return;
    }

    const oldPlainText = stripHtml(change.old_html).trim();
    if (!oldPlainText) {
      context.document.body.insertHtml(change.new_html, Word.InsertLocation.end);
      await context.sync();
      return;
    }

    const searchResults = context.document.body.search(oldPlainText, { matchCase: false });
    searchResults.load("items");
    await context.sync();

    if (searchResults.items.length === 0) {
      throw new Error(
        `Could not find the text to replace in the live document: "${oldPlainText.slice(0, 60)}..."`
      );
    }

    if (change.operation === "delete") {
      searchResults.items[0].delete();
    } else {
      searchResults.items[0].insertHtml(change.new_html, Word.InsertLocation.replace);
    }
    await context.sync();
  });
}

function stripHtml(html) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent || "";
}

async function handleCheckin() {
  const comment = document.getElementById("versionCommentInput").value.trim();
  if (!comment) {
    setStatus("A version comment is required to check in.");
    return;
  }
  try {
    setStatus("Checking in...");
    const result = await api(
      `/matters/${state.matterId}/documents/${state.documentId}/checkin`,
      { method: "POST", body: JSON.stringify({ version_comment: comment }) }
    );
    setStatus(`Checked in as version ${result.new_version}.`);
    await loadVersionHistory();
  } catch (err) {
    if (err.detail?.pending_changes) {
      // The server refused because SuperDocs still has undecided changes on
      // this session - show them instead of just an error string.
      state.pendingChanges = err.detail.pending_changes;
      renderPendingChanges();
    }
    setStatus(`Checkin failed: ${err.message}`);
  }
}

async function loadVersionHistory() {
  try {
    const versions = await api(
      `/matters/${state.matterId}/documents/${state.documentId}/versions`
    );
    const container = document.getElementById("versionsList");
    container.innerHTML = "";
    versions.forEach((v) => {
      const row = document.createElement("div");
      row.className = "version-row";
      row.innerHTML = `
        <span>v${v.version_number} - ${v.comment}</span>
        ${v.has_exported_file ? `<button class="download-btn" data-version="${v.version_number}">Download</button>` : "<span>(no file)</span>"}
      `;
      const downloadBtn = row.querySelector(".download-btn");
      if (downloadBtn) {
        downloadBtn.onclick = () => downloadVersion(v.version_number);
      }
      container.appendChild(row);
    });
  } catch (err) {
    setStatus(`Failed to load version history: ${err.message}`);
  }
}

async function downloadVersion(versionNumber) {
  try {
    setStatus(`Downloading version ${versionNumber}...`);
    const response = await fetch(
      `${API_BASE}/matters/${state.matterId}/documents/${state.documentId}/versions/${versionNumber}/download`,
      { headers: { "X-User-Id": state.userId } }
    );
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ? JSON.stringify(body.detail) : "Download failed");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.documentId}-v${versionNumber}.docx`;
    a.click();
    URL.revokeObjectURL(url);
    setStatus(`Downloaded version ${versionNumber}.`);
  } catch (err) {
    setStatus(`Download failed: ${err.message}`);
  }
}