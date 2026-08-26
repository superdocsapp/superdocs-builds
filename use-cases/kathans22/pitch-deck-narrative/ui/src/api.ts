/** Same-origin `/api` — Vite proxies to FastAPI on :8000 during `npm run dev`. */

export const API_PREFIX = '/api'

export type LedgerEntry = {
  step: string
  vertical: string
  operations: number
  wall_time: number
  status: string
  content_key: string
}

export type LedgerSnapshot = {
  source: string | null
  total_operations: number
  entries: LedgerEntry[]
}

export type GenerateQueued = {
  run_id: string
  status: string
  poll: string
  vertical: string
}

export type RunRecord = {
  run_id?: string
  status: string
  vertical?: string
  force?: boolean
  result?: unknown
  error?: string
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`)
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`${res.status} ${path}: ${detail.slice(0, 240)}`)
  }
  return res.json() as Promise<T>
}

export async function postGenerate(
  vertical: string,
  force: boolean,
): Promise<GenerateQueued> {
  const q = new URLSearchParams({ vertical, force: force ? 'true' : 'false' })
  const res = await fetch(`${API_PREFIX}/generate?${q.toString()}`, {
    method: 'POST',
  })
  const body = (await res.json()) as GenerateQueued & { detail?: string }
  if (!res.ok) {
    throw new Error(
      typeof body.detail === 'string' ? body.detail : `${res.status} /generate`,
    )
  }
  return body
}
