export async function getRunsList(apiBase) {
  const res = await fetch(`${apiBase}/runs`);
  if (!res.ok) throw new Error("Failed to fetch runs list");
  return res.json();
}

export async function getRunDetails(apiBase, runId) {
  const res = await fetch(`${apiBase}/runs/${runId}`);
  if (!res.ok) throw new Error("Failed to fetch run details");
  return res.json();
}

export async function startSubstitutionAnalysis(apiBase, specFile, cutsheetFile, scheduleFile) {
  const formData = new FormData();
  formData.append('spec', specFile);
  formData.append('cutsheet', cutsheetFile);
  formData.append('schedule', scheduleFile);

  const res = await fetch(`${apiBase}/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Analysis failed to start");
  }
  return res.json();
}

export async function approveRun(apiBase, runId) {
  const res = await fetch(`${apiBase}/approve/${runId}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Approval failed");
  }
  return res.json();
}

export async function rejectRun(apiBase, runId) {
  const res = await fetch(`${apiBase}/reject/${runId}`, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Rejection failed");
  }
  return res.json();
}
