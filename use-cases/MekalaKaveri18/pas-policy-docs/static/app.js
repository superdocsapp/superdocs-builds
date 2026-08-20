const $ = (id) => document.getElementById(id);
let jobId = null;

async function loadSample() {
  const r = await fetch("/sample");
  $("json").value = JSON.stringify(await r.json(), null, 2);
}

function render(j) {
  $("status").textContent = `${j.status || ""} ${j.offline ? "(offline — PAS merge, no billed SuperDocs call)" : ""}`;
  $("doc").innerHTML = j.html || "";
  const box = $("changes");
  box.innerHTML = "";
  (j.changes || []).forEach((c) => {
    const el = document.createElement("div");
    el.className = "card";
    el.innerHTML = `<div>${c.ai_explanation || c.operation || "change"}</div>
      <div class="row">
        <button data-id="${c.change_id}" data-ok="true">Approve</button>
        <button data-id="${c.change_id}" data-ok="false">Reject</button>
      </div>`;
    box.appendChild(el);
  });
  const exp = $("export");
  if (j.status === "completed" || j.offline) {
    exp.classList.remove("hidden");
    exp.href = `/jobs/${j.id}/export`;
  }
}

$("load").onclick = loadSample;
$("run").onclick = async () => {
  let policy;
  try {
    policy = JSON.parse($("json").value);
  } catch (e) {
    $("status").textContent = "Invalid JSON";
    return;
  }
  $("status").textContent = "Working… SuperDocs can take minutes on a live key.";
  const r = await fetch("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy, review_mode: $("review").checked }),
  });
  const j = await r.json();
  if (!r.ok) {
    $("status").textContent = j.detail || "failed";
    return;
  }
  jobId = j.id;
  render(j);
};

$("changes").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-id]");
  if (!btn || !jobId) return;
  const r = await fetch(`/jobs/${jobId}/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions: { [btn.dataset.id]: btn.dataset.ok === "true" } }),
  });
  render(await r.json());
});

loadSample();
