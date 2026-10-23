/* Client for the live rehearsal service. The only thing the browser may send is an access code. */
export const API_BASE: string = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '')

export type LiveEvent = { seq: number; time: string; stage: string; status: string; message: string; data: Record<string, any> }
export type LiveStatus = {
  enabled: boolean; busy: boolean; current_run_id: string | null; access_code_required: boolean
  runs_left_today: number; estimated_usd_left_today: number; daily_run_cap: number; daily_usd_cap: number; note: string; cost_note: string
}
export type ApiError = { kind: 'disabled' | 'access_code' | 'busy' | 'quota' | 'rate' | 'network' | 'other'; message: string; currentRunId?: string }

async function j(r: Response): Promise<any> {
  try { return await r.json() } catch { return null }
}

/** Is a live backend reachable here? A static host answers with HTML or 404, which counts as offline. */
export async function fetchStatus(): Promise<{ ok: true; status: LiveStatus } | { ok: false }> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), 5000)
  try {
    const r = await fetch(`${API_BASE}/api/live/status`, { signal: ctl.signal })
    const b = await j(r)
    if (!r.ok || !b || typeof b.enabled !== 'boolean') return { ok: false }
    return { ok: true, status: b as LiveStatus }
  } catch { return { ok: false } } finally { clearTimeout(t) }
}

export async function startRun(accessCode: string): Promise<{ id: string; cancel_token: string } | ApiError> {
  try {
    const r = await fetch(`${API_BASE}/api/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(accessCode ? { access_code: accessCode } : {}) })
    const b = await j(r)
    if (r.ok) return b
    const m = b?.message ?? `The server answered ${r.status}.`
    if (r.status === 503) return { kind: 'disabled', message: m }
    if (r.status === 401) return { kind: 'access_code', message: m }
    if (r.status === 409) return { kind: 'busy', message: m, currentRunId: b?.current_run_id }
    if (r.status === 429) return { kind: b?.error === 'rate_limited' ? 'rate' : 'quota', message: m }
    return { kind: 'other', message: m }
  } catch { return { kind: 'network', message: 'Could not reach the live server.' } }
}

export async function cancelRun(id: string, token: string): Promise<boolean> {
  try { return (await fetch(`${API_BASE}/api/runs/${id}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ cancel_token: token }) })).ok } catch { return false }
}

export async function fetchReport(id: string): Promise<any | null> {
  try { const r = await fetch(`${API_BASE}/api/runs/${id}/report`); return r.ok ? await r.json() : null } catch { return null }
}

/** Server-sent events, replayable from the first event (a page refresh re-attaches to the same run). */
export function openStream(id: string, onEvent: (e: LiveEvent) => void, onLost: () => void): () => void {
  const es = new EventSource(`${API_BASE}/api/runs/${id}/events`)
  let ended = false
  const handle = (m: MessageEvent) => { try { const e = JSON.parse(m.data) as LiveEvent; onEvent(e); if (e.stage === 'end') { ended = true; es.close() } } catch { /* ignore a malformed frame */ } }
  es.addEventListener('message', handle as EventListener)
  es.addEventListener('end', handle as EventListener)
  es.onerror = () => { if (!ended && es.readyState === EventSource.CLOSED) onLost() }
  return () => es.close()
}
