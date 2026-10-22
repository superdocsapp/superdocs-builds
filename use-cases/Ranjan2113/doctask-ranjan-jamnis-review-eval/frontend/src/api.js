const BASE = import.meta.env?.VITE_API_BASE || 'http://127.0.0.1:8000';

async function request(path, options = {}) {
  const response = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${options.method || 'GET'} ${path} failed (${response.status}): ${body}`);
  }
  return response.json();
}

export const api = {
  health: () => request('/api/health'),
  startSession: (reviewerId) =>
    request('/api/session/start', {
      method: 'POST',
      body: JSON.stringify({ reviewer_id: reviewerId }),
    }),
  getBatch: (batchId, condition) =>
    request(`/api/batch/${encodeURIComponent(batchId)}?condition=${encodeURIComponent(condition)}`),
  /**
   * Record one decision. Timestamps come from the client clock; the server
   * recomputes the duration from them rather than trusting a client-side
   * elapsed number.
   */
  recordDecision: (payload) =>
    request('/api/decision', { method: 'POST', body: JSON.stringify(payload) }),
};
