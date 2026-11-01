const $ = (id) => document.getElementById(id);
let jobId = null;

function payload() {
  return {
    title: $("title").value,
    author: $("author").value,
    overview: $("overview").value,
    audience: $("audience").value,
    chapters: $("chapters").value,
    search_query: $("audience").value,
    review_mode: $("review").checked,
    sample: false,
  };
}

function renderComps(hits) {
  $("comps").innerHTML = hits
    .map(
      (c) =>
        `<li><strong>${c.title}</strong> — ${c.author} (${c.year}, ${c.publisher}). ${c.why_comp}</li>`
    )
    .join("");
}

function renderJob(j) {
  const waiting = j.status === "awaiting_approval";
  const left = (j.changes || []).length;
  $("status").textContent = waiting
    ? `Decide every section. ${left} still waiting. Approved text lands in the document; rejected stays the placeholder.`
    : `${j.status || ""}`;
  $("doc").innerHTML = j.html || "";
  const box = $("changes");
  box.innerHTML = "";
  const reg = document.createElement("div");
  reg.className = "card";
  reg.innerHTML = "<div class='kicker'>Register</div>" + (j.register || [])
    .map((r) => {
      const d = r.decision === true ? "approved" : r.decision === false ? "rejected" : "pending";
      return `<div>${r.label}: <strong>${d}</strong></div>`;
    })
    .join("");
  box.appendChild(reg);
  (j.changes || []).forEach((c) => {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<p>${c.ai_explanation || c.operation || "section"}</p>
      <div class="diff"><div><span class="kicker">If rejected (stays)</span>${c.old_html || ""}</div>
      <div><span class="kicker">If approved (fills)</span>${c.new_html || ""}</div></div>
      <div class="row">
        <button data-id="${c.change_id}" data-ok="true">Approve this section</button>
        <button data-id="${c.change_id}" data-ok="false">Reject this section</button>
      </div>`;
    box.appendChild(el);
  });
  const exp = $("export");
  if (j.status === "completed") {
    exp.classList.remove("hidden");
    exp.href = `/jobs/${j.id}/export`;
  } else {
    exp.classList.add("hidden");
  }
}

$("search").onclick = async () => {
  const r = await fetch("/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query: $("audience").value, limit: 3 }),
  });
  const data = await r.json();
  renderComps(data.hits || []);
};

$("run").onclick = async () => {
  $("status").textContent = "Working…";
  const r = await fetch("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload()),
  });
  const j = await r.json();
  if (!r.ok) {
    $("status").textContent = j.detail || "failed";
    return;
  }
  jobId = j.id;
  renderComps(j.comps || []);
  renderJob(j);
};

document.getElementById("changes").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-id]");
  if (!btn || !jobId) return;
  const r = await fetch(`/jobs/${jobId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions: { [btn.dataset.id]: btn.dataset.ok === "true" } }),
  });
  renderJob(await r.json());
});
