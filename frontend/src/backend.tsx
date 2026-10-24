import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { API_BASE } from './live/api'

type Health = { status: string; live_enabled?: boolean; pipeline_enabled?: boolean; verify_enabled?: boolean; pipeline_version?: string; pipeline_tag?: string; server_time_utc?: string }
export type BackendState = { state: 'checking' | 'waking' | 'online' | 'offline'; health?: Health; liveEnabled?: boolean; pipelineEnabled?: boolean; verifyEnabled?: boolean; checkedAt?: number; wakeStartedAt?: number; refresh: () => void }
const Ctx = createContext<BackendState>({ state: 'checking', refresh: () => {} })
export const useBackend = () => useContext(Ctx)

/** How long a sleeping free host may take to come back before the site gives up and shows offline mode. */
export const WAKE_LIMIT_MS = 90_000
const WAKE_RETRY_MS = 3000

type Probe = { kind: 'ok'; health: Health } | { kind: 'absent' } | { kind: 'down' }

async function getJson(path: string, ms = 8000): Promise<{ status: number; body: any | null } | null> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  try {
    const r = await fetch(`${API_BASE}${path}`, { signal: ctl.signal })
    return { status: r.status, body: await r.json().catch(() => null) }
  } catch { return null } finally { clearTimeout(t) }
}

/** ok: the health check answered. absent: this origin answers but has no backend (a static host: 404 or HTML), so waiting is pointless.
 *  down: no answer, a timeout or a 5xx: what a sleeping or starting host looks like. */
async function probe(): Promise<Probe> {
  const r = await getJson('/api/health')
  if (!r) return { kind: 'down' }
  if (r.status >= 500) return { kind: 'down' }
  if (r.status === 200 && r.body && r.body.status === 'ok') return { kind: 'ok', health: r.body }
  return { kind: 'absent' }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Polls /api/health. It says "online" only after health has succeeded. If the backend does not answer it retries for up to 90 s
 *  ("waking up"), then falls back to offline mode; a host that answers with a 404 or HTML is offline at once. */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [st, setSt] = useState<Omit<BackendState, 'refresh'>>({ state: 'checking' })
  const token = useRef(0)
  const stateRef = useRef<BackendState['state']>('checking')
  stateRef.current = st.state

  const online = useCallback(async (h: Health) => {
    const l = await getJson('/api/live/status', 5000)
    const liveEnabled = l && l.body && typeof l.body.enabled === 'boolean' ? !!l.body.enabled : !!h.live_enabled
    const pipelineEnabled = l && l.body && typeof l.body.pipeline_enabled === 'boolean' ? !!l.body.pipeline_enabled : h.pipeline_enabled !== false
    setSt({ state: 'online', health: h, liveEnabled, pipelineEnabled, verifyEnabled: h.verify_enabled !== false, checkedAt: Date.now() })
  }, [])

  /** startWaking: begin the 90 s retry window when nothing answers (first load, a manual refresh, or a host that went to sleep). */
  const check = useCallback(async (startWaking: boolean) => {
    const my = ++token.current
    const t0 = Date.now()
    for (;;) {
      const p = await probe()
      if (my !== token.current) return
      if (p.kind === 'ok') return online(p.health)
      if (p.kind === 'absent' || !startWaking || Date.now() - t0 > WAKE_LIMIT_MS) { setSt({ state: 'offline', checkedAt: Date.now() }); return }
      setSt((s) => ({ state: 'waking', wakeStartedAt: s.wakeStartedAt ?? t0, checkedAt: Date.now() }))
      await sleep(WAKE_RETRY_MS)
      if (my !== token.current) return
    }
  }, [online])

  const refresh = useCallback(() => { check(true) }, [check])
  useEffect(() => {
    check(true)
    // later polls: a single probe while offline (it may have come up), a new wake window if an online host stops answering
    const t = setInterval(() => { if (stateRef.current === 'online') check(true); else if (stateRef.current === 'offline') check(false) }, 20000)
    const vis = () => document.visibilityState === 'visible' && stateRef.current !== 'waking' && stateRef.current !== 'checking' && check(stateRef.current === 'online')
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis); token.current++ }
  }, [check])
  const value = useMemo(() => ({ ...st, refresh }), [st, refresh])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

function useElapsed(since?: number) {
  const [, tick] = useState(0)
  useEffect(() => { if (!since) return; const t = setInterval(() => tick((n) => n + 1), 1000); return () => clearInterval(t) }, [since])
  return since ? Math.max(0, Math.round((Date.now() - since) / 1000)) : 0
}

/** Shown on pages that need the backend while it is waking up. */
export function WakingNote({ className = '' }: { className?: string }) {
  const b = useBackend()
  const s = useElapsed(b.wakeStartedAt)
  return (
    <div role="status" className={`rounded-xl border border-amber/40 bg-amber/[.07] p-4 text-sm ${className}`}>
      <b className="text-amber">Backend waking up (about 1 minute).</b> The free host sleeps when idle. Waiting {s} s of up to {Math.round(WAKE_LIMIT_MS / 1000)} s; if it does not answer, the site switches to offline mode with recorded data.
    </div>
  )
}

/** Navbar pill: "Backend online" only after the health check succeeded; "Backend waking up" while retrying; or "Backend offline, showing recorded data". */
export function BackendBadge() {
  const b = useBackend()
  const secs = useElapsed(b.state === 'waking' ? b.wakeStartedAt : undefined)
  if (b.state === 'checking') return <span className="chip hidden sm:inline-flex" aria-live="polite"><span className="h-2 w-2 rounded-full bg-dim/60" aria-hidden />checking backend...</span>
  if (b.state === 'waking') {
    return (
      <span className="chip !border-amber/40 !text-amber" title="The host is waking from sleep. The site retries for up to 90 seconds, then falls back to offline mode." aria-live="polite">
        <span className="h-2 w-2 animate-pulse rounded-full bg-amber" aria-hidden /><span className="hidden md:inline">Backend waking up (about 1 minute) | {secs} s</span><span className="hidden sm:inline md:hidden">Waking up</span><span className="sr-only sm:hidden">Backend waking up, about 1 minute</span>
      </span>
    )
  }
  if (b.state === 'offline') {
    return (
      <button onClick={b.refresh} className="chip !border-amber/40 !text-amber hover:!bg-amber/10" title="No live backend answered. Everything shown is a stored artifact. Click to check again." aria-live="polite">
        <span className="h-2 w-2 rounded-full bg-amber" aria-hidden /><span className="hidden md:inline">Backend offline, showing recorded data</span><span className="hidden sm:inline md:hidden">Offline</span><span className="sr-only sm:hidden">Backend offline, showing recorded data</span>
      </button>
    )
  }
  const t = b.health?.server_time_utc?.slice(11, 19)
  return (
    <button onClick={b.refresh} className="chip !border-phos/40 !text-phos hover:!bg-phos/10" title={`Backend online. Pipeline ${b.health?.pipeline_version ?? '?'} (${b.health?.pipeline_tag ?? 'tag unknown'}). Live runs ${b.liveEnabled ? 'enabled' : 'switched off'}${b.pipelineEnabled === false ? ', full pipeline runs switched off on this host' : ''}. Click to refresh.`} aria-live="polite">
      <span className="h-2 w-2 animate-pulse rounded-full bg-phos" aria-hidden />
      <span className="hidden md:inline">Backend online{b.health?.pipeline_tag ? ` | ${b.health.pipeline_tag}` : ''}{t ? ` | ${t} UTC` : ''}</span><span className="hidden sm:inline md:hidden">Online</span><span className="sr-only sm:hidden">Backend online</span>
    </button>
  )
}
