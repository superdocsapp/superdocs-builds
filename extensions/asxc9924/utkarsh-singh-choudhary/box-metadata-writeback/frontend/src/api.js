// Thin fetch wrapper around the FastAPI backend. Every function here maps
// 1:1 to a real endpoint in app/api/main.py -- nothing in this file
// fabricates data; if the backend doesn't have it, the UI doesn't show it.

export const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const API_KEY_STORAGE_KEY = "ledger.apiKey";

export function getApiKey() {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE_KEY) || import.meta.env.VITE_API_KEY || "";
  } catch {
    return import.meta.env.VITE_API_KEY || "";
  }
}

export function setApiKey(key) {
  try {
    if (key) sessionStorage.setItem(API_KEY_STORAGE_KEY, key);
    else sessionStorage.removeItem(API_KEY_STORAGE_KEY);
  } catch {
    /* sessionStorage unavailable (e.g. private browsing edge cases) --
       the key still works for the current page load via the closure
       default from VITE_API_KEY, just won't persist across reloads. */
  }
}

async function request(path, options = {}) {
  const key = getApiKey();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
    },
    ...options,
  });
  if (res.status === 401) {
    throw new AuthError("Unauthorized — check your API key.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export class AuthError extends Error {}

export const api = {
  health: () => request("/healthz"),
  listFiles: () => request("/files"),
  fileDetail: (fileId) => request(`/files/${encodeURIComponent(fileId)}`),
  fileHistory: (fileId) => request(`/files/${encodeURIComponent(fileId)}/history`),
  fileCost: (fileId) => request(`/runs/${encodeURIComponent(fileId)}/cost`),
  governanceOutcome: (fileId) => request(`/files/${encodeURIComponent(fileId)}/governance-outcome`),
  reviews: (fileId) => request(`/reviews${fileId ? `?file_id=${encodeURIComponent(fileId)}` : ""}`),
  approveReview: (reviewId) => request(`/reviews/${encodeURIComponent(reviewId)}/approve`, { method: "POST" }),
  rejectReview: (reviewId) => request(`/reviews/${encodeURIComponent(reviewId)}/reject`, { method: "POST" }),
  search: (params) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    ).toString();
    return request(`/search${qs ? `?${qs}` : ""}`);
  },
  templates: () => request("/templates"),
  metrics: async () => {
    // /metrics is Prometheus plain-text exposition format, not JSON --
    // deliberately bypasses the JSON-parsing `request()` helper above.
    const key = getApiKey();
    const res = await fetch(`${API_BASE}/metrics`, {
      headers: key ? { Authorization: `Bearer ${key}` } : {},
    });
    if (res.status === 401) throw new AuthError("Unauthorized — check your API key.");
    if (!res.ok) throw new Error(res.statusText);
    return res.text();
  },
  processFile: (fileId) => request(`/process/${encodeURIComponent(fileId)}`, { method: "POST" }),
  seedDemo: () => request("/demo/seed", { method: "POST" }),
};
