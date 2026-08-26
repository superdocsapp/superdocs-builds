// Thin fetch wrapper for the FastAPI backend (src/localizer/api/routes.py).
// Every screen but Integrity (which reads the static evidence snapshot)
// goes through this. Requests go to /api/*, proxied to the backend in dev
// (see vite.config.ts) — the browser never needs CORS configured.

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail ?? res.statusText;
    throw new ApiError(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}
