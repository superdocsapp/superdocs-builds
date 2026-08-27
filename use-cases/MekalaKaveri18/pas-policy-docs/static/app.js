const $ = (id) => document.getElementById(id);
let jobId = null;

const FALLBACK_SAMPLE = {
  source_system: "Guidewire PolicyCenter (fictional)",
  policy_number: "PC-2026-88421",
  named_insured: "Harbor & Pine Bakery LLC",
  endorsement_effective_date: "2026-09-01",
  coverages: [
    {
      line: "Commercial General Liability",
      code: "CGL",
      limit: "USD 1,000,000 per occurrence / USD 2,000,000 aggregate",
    },
    {
      line: "Business Personal Property",
      code: "BPP",
      limit: "USD 250,000 blanket, replacement cost",
    },
  ],
};

function showSample(policy) {
  $("json").value = JSON.stringify(policy, null, 2);
}

async function loadSample(thenGenerate) {
  $("status").textContent = "Loading sample…";
  let policy = FALLBACK_SAMPLE;
  try {
    const r = await fetch("/sample");
    if (r.ok) policy = await r.json();
  } catch (e) {
    /* keep fallback */
  }
  showSample(policy);
  $("status").textContent = thenGenerate
    ? "Sample payload loaded. Drafting endorsement…"
    : "Sample payload loaded (Harbor & Pine Bakery). Click Generate for the wording.";
  if (thenGenerate) await generate(policy);
}

async function generate(policy) {
  if (!policy) {
    try {
      policy = JSON.parse($("json").value);
    } catch (e) {
      $("status").textContent = "Invalid JSON. Click Load sample, then Generate.";
      return;
    }
  }
  $("status").textContent = "Working…";
  const r = await fetch("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ policy, review_mode: $("review").checked, sample: true }),
  });
  const j = await r.json();
  if (!r.ok) {
    $("status").textContent = j.detail || "failed";
    return;
  }
  jobId = j.id;
  render(j);
}

function render(j) {
  const waiting = j.status === "awaiting_approval";
  const left = (j.changes || []).length;
  $("status").textContent = waiting
    ? `Decide every section. ${left} still waiting. Approved lines land; rejected stay placeholders.`
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

$("load").onclick = () => loadSample(true);
$("run").onclick = () => generate();

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

loadSample(false);
