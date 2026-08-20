// Centralized API layer. Every error leaves here as a human-readable
// ApiError — never a raw object, never "[object Object]".

export class ApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

// FastAPI validation errors arrive as detail: [{loc, msg, type}] — an
// array whose String() would be "[object Object]". Render a meaningful
// message instead.
export function errorMessage(res, body) {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
    return msgs || `Request failed (${res.status})`
  }
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  if (res?.status === 403) {
    return (
      'Google Classroom rejected the operation. This usually means the ' +
      'assignment was created outside this app’s Google project — ' +
      'Classroom only allows attachment changes on API-created assignments.'
    )
  }
  return `Request failed (${res.status})`
}

export async function api(path, options = {}) {
  let res
  try {
    res = await fetch(path, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError(
      'Network error — could not reach the Classmark server. Is it still running?',
      0
    )
  }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new ApiError(errorMessage(res, body), res.status, body.detail ?? null)
  }
  return body
}
