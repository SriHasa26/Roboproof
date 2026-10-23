import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { API_BASE } from './live/api'

type Health = { status: string; live_enabled?: boolean; pipeline_version?: string; pipeline_tag?: string; server_time_utc?: string }
export type BackendState = { state: 'checking' | 'online' | 'offline'; health?: Health; liveEnabled?: boolean; checkedAt?: number; refresh: () => void }
const Ctx = createContext<BackendState>({ state: 'checking', refresh: () => {} })
export const useBackend = () => useContext(Ctx)

async function getJson(path: string, ms = 4000): Promise<any | null> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), ms)
  try {
    const r = await fetch(`${API_BASE}${path}`, { signal: ctl.signal })
    return r.ok ? await r.json().catch(() => null) : null
  } catch { return null } finally { clearTimeout(t) }
}

/** Polls /api/health and /api/live/status so every page can say honestly whether a live backend is there. */
export function BackendProvider({ children }: { children: ReactNode }) {
  const [st, setSt] = useState<Omit<BackendState, 'refresh'>>({ state: 'checking' })
  const refresh = useCallback(async () => {
    const [h, l] = await Promise.all([getJson('/api/health'), getJson('/api/live/status')])
    if (h && h.status === 'ok') setSt({ state: 'online', health: h, liveEnabled: l ? !!l.enabled : !!h.live_enabled, checkedAt: Date.now() })
    else setSt({ state: 'offline', checkedAt: Date.now() })
  }, [])
  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 20000)
    const vis = () => document.visibilityState === 'visible' && refresh()
    document.addEventListener('visibilitychange', vis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', vis) }
  }, [refresh])
  const value = useMemo(() => ({ ...st, refresh }), [st, refresh])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

/** Navbar pill: "Backend online" with the pipeline tag and server time, or "Backend offline, showing recorded data". */
export function BackendBadge() {
  const b = useBackend()
  if (b.state === 'checking') return <span className="chip hidden sm:inline-flex" aria-live="polite"><span className="h-2 w-2 rounded-full bg-dim/60" aria-hidden />checking backend...</span>
  if (b.state === 'offline') {
    return (
      <button onClick={b.refresh} className="chip !border-amber/40 !text-amber hover:!bg-amber/10" title="No live backend answered. Everything shown is a stored artifact. Click to check again." aria-live="polite">
        <span className="h-2 w-2 rounded-full bg-amber" aria-hidden /><span className="hidden md:inline">Backend offline, showing recorded data</span><span className="hidden sm:inline md:hidden">Offline</span><span className="sr-only sm:hidden">Backend offline, showing recorded data</span>
      </button>
    )
  }
  const t = b.health?.server_time_utc?.slice(11, 19)
  return (
    <button onClick={b.refresh} className="chip !border-phos/40 !text-phos hover:!bg-phos/10" title={`Backend online. Pipeline ${b.health?.pipeline_version ?? '?'} (${b.health?.pipeline_tag ?? 'tag unknown'}). Live runs ${b.liveEnabled ? 'enabled' : 'switched off'}. Click to refresh.`} aria-live="polite">
      <span className="h-2 w-2 animate-pulse rounded-full bg-phos" aria-hidden />
      <span className="hidden md:inline">Backend online{b.health?.pipeline_tag ? ` | ${b.health.pipeline_tag}` : ''}{t ? ` | ${t} UTC` : ''}</span><span className="hidden sm:inline md:hidden">Online</span><span className="sr-only sm:hidden">Backend online</span>
    </button>
  )
}
