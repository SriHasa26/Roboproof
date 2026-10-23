import { API_BASE } from '../live/api'

export type ParamSpec = { name: string; label: string; unit: string; help: string; min: number; max: number; integer: boolean; default?: number | null; tunable?: boolean; note?: string | null }
export type Preset = { id: string; label: string; scenario: Record<string, number> | null; policy: Record<string, number> | null }
export type Spec = {
  scenario: ParamSpec[]; policy: ParamSpec[]; presets: Preset[]; max_sweep_n: number; seed: { min: number; max: number; default: number }
  task: string; label: string; limits: string; enabled: boolean; analyze_available: boolean; analyze_access_code_required: boolean; analyze_est_usd: number
  batch?: { max_rows: number; max_kb: number; columns: string[]; template_url: string }
  interpret_available?: boolean; interpret_max_chars?: number; interpret_est_usd?: number
}
export type RowError = { row: number; line: number; field: string; problem: string }
export type PgError = { kind: 'invalid' | 'busy' | 'rate' | 'disabled' | 'timeout' | 'auth' | 'network' | 'other'; message: string; errors?: RowError[] }

export async function fetchSpec(): Promise<Spec | null> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), 5000)
  try {
    const r = await fetch(`${API_BASE}/api/sim/spec`, { signal: ctl.signal })
    const b = await r.json().catch(() => null)
    return r.ok && b && Array.isArray(b.scenario) ? (b as Spec) : null
  } catch { return null } finally { clearTimeout(t) }
}

export async function post<T>(path: string, body: unknown, timeoutMs: number): Promise<{ ok: true; data: T } | { ok: false; error: PgError }> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const r = await fetch(`${API_BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal })
    const b = await r.json().catch(() => null)
    if (r.ok) return { ok: true, data: b as T }
    const m: string = b?.message ?? `The server answered ${r.status}.`
    const kind: PgError['kind'] = r.status === 422 || r.status === 413 ? 'invalid' : r.status === 429 ? 'rate' : r.status === 401 ? 'auth' : r.status === 504 ? 'timeout' : b?.error === 'busy' ? 'busy' : b?.error === 'disabled' ? 'disabled' : 'other'
    return { ok: false, error: { kind, message: m, ...(Array.isArray(b?.errors) ? { errors: b.errors } : {}) } }
  } catch { return { ok: false, error: { kind: 'network', message: 'Could not reach the simulator backend.' } } } finally { clearTimeout(t) }
}

export const errTitle: Record<PgError['kind'], string> = {
  invalid: 'Check the inputs', busy: 'Simulator busy', rate: 'Rate limited', disabled: 'Switched off', timeout: 'Took too long', auth: 'Access code needed', network: 'Network error', other: 'Could not run',
}
