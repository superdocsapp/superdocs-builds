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
  $("status").textContent = `${j.status || ""} ${j.offline ? "(offline sample — no SuperDocs key billed)" : ""}`;
  $("doc").innerHTML = j.html || "";
  const box = $("changes");
  box.innerHTML = "";
  (j.changes || []).forEach((c) => {
    const id = c.change_id;
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div>${c.operation || "edit"} · ${c.ai_explanation || ""}</div>
      <div class="row">
        <button data-id="${id}" data-ok="true">Approve</button>
        <button data-id="${id}" data-ok="false">Reject</button>
      </div>`;
    box.appendChild(el);
  });
  const exp = $("export");
  if (j.status === "completed" || j.offline) {
    exp.classList.remove("hidden");
    exp.href = `/jobs/${j.id}/export`;
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
  $("status").textContent = "Working… large SuperDocs edits can take minutes.";
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
  const decisions = { [btn.dataset.id]: btn.dataset.ok === "true" };
  const r = await fetch(`/jobs/${jobId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions }),
  });
  renderJob(await r.json());
});
