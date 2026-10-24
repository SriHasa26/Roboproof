import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Summary, load, pct, usd, useData } from '../lib'
import { Skeleton, useToast, usePageTitle } from '../motion'
import { WakingNote, useBackend } from '../backend'
import { RatePair, SourceChip, Stamp } from '../ui'
import { ApiError, LiveEvent, LiveStatus, cancelRun, fetchStatus, openStream, startRun } from '../live/api'
import { derive } from '../live/derive'
import { Candidates, Confirm, GateLights, Terminal, Timeline } from '../live/parts'

type Source = { kind: 'live'; id: string; token: string | null } | { kind: 'replay'; key: string }
type StatusX = LiveStatus & { pipeline_enabled?: boolean }
type ReplayMeta = { key: string; run_id: string; has_calls: boolean; date: string; verdict: string | null; duration_s: number; estimated_cost_usd: number | null; master_seed: number | null; n_events: number; note?: string }
const KEY = 'roboproof.live'

const fmtS = (s: number) => (s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${s.toFixed(0)} s`)

function useReplays() {
  const [list, set] = useState<ReplayMeta[] | null | undefined>(undefined)
  useEffect(() => { load<ReplayMeta[]>('live_replay/index.json').then((l) => set(Array.isArray(l) && l.length ? l : null)).catch(() => set(null)) }, [])
  return list
}

function errText(e: ApiError): [string, string] {
  switch (e.kind) {
    case 'busy': return ['Busy', 'Another live run is in progress. Only one run can go at a time. Try again in a few minutes, or watch it below.']
    case 'quota': return ['Quota reached', e.message]
    case 'rate': return ['Slow down', e.message]
    case 'disabled': return ['Live runs are switched off', 'The server operator has turned live runs off. You can still replay a recorded run.']
    case 'access_code': return ['Access code needed', e.message]
    case 'network': return ['Network error', 'Could not reach the live server. Check your connection and try again.']
    default: return ['Could not start', e.message]
  }
}

export default function Live() {
  usePageTitle('Live console')
  const toast = useToast()
  const off = useData<Summary>('official.json')
  const replays = useReplays()
  const be = useBackend()
  const [probe, setProbe] = useState<'checking' | 'online' | 'offline'>('checking')
  const [status, setStatus] = useState<StatusX | null>(null)
  const [source, setSource] = useState<Source | null>(null)
  const [events, setEvents] = useState<LiveEvent[]>([])
  const [lost, setLost] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [code, setCode] = useState('')
  const [err, setErr] = useState<ApiError | null>(null)
  const [starting, setStarting] = useState(false)
  const [speed, setSpeed] = useState(8)
  const [replayKey, setReplayKey] = useState(0)

  const refresh = useCallback(async () => {
    const r = await fetchStatus()
    if (r.ok) { setStatus(r.status); setProbe('online'); return r.status }
    setProbe('offline'); setStatus(null); return null
  }, [])

  // probe the backend, and re-attach to a run this tab started before a refresh
  useEffect(() => {
    if (be.state === 'offline') { setProbe('offline'); setStatus(null); return }
    if (be.state !== 'online') { setProbe('checking'); return }  // checking or waking: the shared health check decides
    let live = true
    refresh().then((s) => {
      if (!live || !s) return
      try {
        const saved = JSON.parse(sessionStorage.getItem(KEY) ?? 'null')
        if (saved?.id) setSource({ kind: 'live', id: saved.id, token: saved.token ?? null })
      } catch { /* no saved run */ }
    })
    return () => { live = false }
  }, [refresh, be.state])

  // live stream
  useEffect(() => {
    if (source?.kind !== 'live') return
    setEvents([]); setLost(false)
    const close = openStream(source.id, (e) => setEvents((xs) => (xs.some((x) => x.seq === e.seq) ? xs : [...xs, e])), () => setLost(true))
    return close
  }, [source, replayKey])

  // recorded replay of a real run: same events, played back with the original relative timing (sped up)
  useEffect(() => {
    if (source?.kind !== 'replay') return
    setEvents([]); setLost(false)
    let stop = false, timer: ReturnType<typeof setTimeout>
    load<LiveEvent[]>(`live_replay/${source.key}/events.json`).then((all) => {
      const t = (i: number) => Date.parse(all[i].time)
      const step = (i: number) => {
        if (stop || i >= all.length) return
        setEvents(all.slice(0, i + 1))
        if (i + 1 < all.length) timer = setTimeout(() => step(i + 1), Math.min(Math.max(t(i + 1) - t(i), 0) / speed, 2500))
      }
      step(0)
    }).catch(() => toast('Could not load the recorded replay.', 'warn'))
    return () => { stop = true; clearTimeout(timer) }
  }, [source, speed, replayKey, toast])

  const view = useMemo(() => derive(events), [events])
  const running = events.length > 0 && !view.ended
  const live = source?.kind === 'live'

  useEffect(() => { if (view.ended && live) { refresh(); try { sessionStorage.removeItem(KEY) } catch { /* ignore */ } } }, [view.ended, live, refresh])

  const begin = async () => {
    setStarting(true); setErr(null)
    const r = await startRun(code.trim())
    setStarting(false); setConfirm(false)
    if ('kind' in r) { setErr(r); refresh(); return }
    try { sessionStorage.setItem(KEY, JSON.stringify({ id: r.id, token: r.cancel_token })) } catch { /* ignore */ }
    setSource({ kind: 'live', id: r.id, token: r.cancel_token })
    refresh()
  }
  const cancel = async () => {
    if (source?.kind !== 'live' || !source.token) return
    toast((await cancelRun(source.id, source.token)) ? 'Cancel requested.' : 'Could not cancel.', 'info')
  }
  const reset = () => { setSource(null); setEvents([]); setErr(null); refresh() }

  const agg: any = off.data?.aggregate
  const typical = agg ? { t: agg.wall_clock_total_s, c: agg.estimated_cost_usd } : null
  const download = () => {
    const blob = new Blob([JSON.stringify({ kind: source?.kind === 'replay' ? 'recorded replay' : 'live rehearsal', run_id: source?.kind === 'live' ? source.id : null, events, derived: { verdict: view.verdict, gates: view.gates, metrics: view.metrics, attempts: view.attempts } }, null, 1)], { type: 'application/json' })
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `roboproof_${source?.kind === 'live' ? source.id : 'replay'}.json`; a.click(); URL.revokeObjectURL(a.href)
  }

  const meta = source?.kind === 'replay' ? replays?.find((r) => r.key === source.key) : undefined
  const replayBtn = replays ? (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Recorded live runs">
      {replays.map((r) => <button key={r.key} className="btn btn-ghost" onClick={() => { setSource({ kind: 'replay', key: r.key }); setReplayKey((k) => k + 1) }}>Replay: {r.verdict ?? 'run'}, {r.date}</button>)}
    </div>
  ) : null

  return (
    <div>
      <div className="eyebrow mb-3">live console</div>
      <h1 className="font-display">Run the real pipeline.</h1>
      <p className="mt-3 max-w-2xl text-lg text-dim">A live rehearsal runs the actual pipeline end to end: real Nemotron calls on Nebius Token Factory, real PyBullet simulation in a local container, a real deterministic gate.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <span className="chip !border-amber/40 !text-amber">REHEARSAL, NOT OFFICIAL</span><span className="chip">rehearsal seeds only, held-out seeds never touched</span><span className="chip">LOCAL FALLBACK, not Nebius Serverless Jobs</span>
      </div>

      {!source && (
        <div className="mt-8 grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          {probe === 'checking' && (be.state === 'waking' ? <WakingNote /> : <Skeleton className="h-64" />)}
          {probe === 'offline' && (
            <div className="glass border-amber/30 p-6">
              <div className="eyebrow !text-amber mb-2">offline</div>
              <h2 className="font-display">Live runs are offline in this deployment.</h2>
              <p className="mt-3 text-dim">This copy of the site is static and has no backend, so it cannot start a run. Live runs need the backend container (see the README, &ldquo;Running live&rdquo;). You can still watch a recording of a real live run.</p>
              <div className="mt-5">{replayBtn ?? <span className="text-sm text-dim">No recorded live run is included in this build.</span>}</div>
            </div>
          )}
          {probe === 'online' && status && (!status.enabled || status.pipeline_enabled === false) && (
            <div className="glass border-amber/30 p-6">
              <div className="eyebrow !text-amber mb-2">runs are off on this host</div>
              <h2 className="font-display">Full pipeline runs are not available here.</h2>
              <p className="mt-3 text-dim">
                {status.enabled ? 'This is a small free instance, so full pipeline runs are switched off on it.' : 'Live runs are switched off on this server.'} Full pipeline runs are available when you run the project locally, see the README, &ldquo;Running live&rdquo;.
                {status.enabled ? ' The playground (scenario, sweep, batch, plain-English input and analysis) still works here.' : ''} You can watch recordings of real live runs:
              </p>
              <div className="mt-5">{replayBtn}</div>
            </div>
          )}
          {probe === 'online' && status && status.enabled && status.pipeline_enabled !== false && (
            <div className="glass p-6">
              <h2 className="font-display">Start a live rehearsal</h2>
              {typical ? (
                <ul className="mt-3 space-y-1.5 text-sm text-dim">
                  <li>Typical time: about <b className="text-text">{fmtS(typical.t.median)}</b> (range {fmtS(typical.t.min)} to {fmtS(typical.t.max)}) in the 5 recorded official-batch runs.</li>
                  <li>Typical cost: about <b className="text-text">{usd(typical.c.median)}</b> (range {usd(typical.c.min)} to {usd(typical.c.max)}). <i>Estimates from token counts times API prices; billing is not checked.</i></li>
                  <li>The result can be VERIFIED, FAILED or UNVERIFIED. It is never an official result, whatever it says.</li>
                </ul>
              ) : <Skeleton className="mt-3 h-16" />}
              <div className="mt-4 flex flex-wrap gap-2 font-mono text-[11px]">
                <span className="chip">{status.runs_left_today} of {status.daily_run_cap} runs left today</span>
                <span className="chip">~${status.estimated_usd_left_today.toFixed(2)} estimated spend left today</span>
                <span className={`chip ${status.busy ? '!border-verm/50 !text-verm' : ''}`}>{status.busy ? 'busy: a run is in progress' : 'idle'}</span>
              </div>
              {(
                <>
                  {status.access_code_required && (
                    <label className="mt-5 block text-sm">Access code<input type="password" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off"
                      className="mt-1 block w-full rounded-lg border border-white/15 bg-black/30 px-3 py-2 font-mono text-sm outline-none focus:border-amber" /></label>
                  )}
                  <div className="mt-5 flex flex-wrap gap-3">
                    <button className="btn btn-primary" onClick={() => setConfirm(true)} disabled={status.busy || status.runs_left_today <= 0}>Start live rehearsal</button>
                    {status.busy && status.current_run_id && <button className="btn btn-ghost" onClick={() => setSource({ kind: 'live', id: status.current_run_id!, token: null })}>Watch the current run</button>}
                    {replayBtn}
                  </div>
                </>
              )}
              {err && (() => { const [t, m] = errText(err); return <div role="alert" className="mt-5 rounded-lg border border-verm/40 bg-verm/[.07] p-3 text-sm"><b className="text-verm">{t}.</b> {m}</div> })()}
            </div>
          )}
          {!(probe === 'online' && status && (!status.enabled || status.pipeline_enabled === false)) && (
          <div className="glass p-6">
            <h3 className="font-display">What you will see</h3>
            <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-dim">
              <li>The seven stages light up as each one finishes.</li>
              <li>A log of real events: model calls with latency and tokens, artifacts as they are written.</li>
              <li>The candidate patches code measured, with the selected one marked.</li>
              <li>The gate checks G1 to G6. The pipeline writes these together at the end of the run, so they appear together.</li>
              <li>The verdict and the before and after metrics.</li>
            </ol>
            {replays && probe === 'online' && <p className="mt-4 text-xs text-dim">Recordings of real live runs ({replays.map((r) => `${r.verdict} ${r.date}`).join(' and ')}) are also available to replay.</p>}
          </div>
          )}
        </div>
      )}

      {confirm && (
        <Confirm title="Start a real live run?" confirm={starting ? 'Starting...' : 'Yes, start it'} busy={starting} onConfirm={begin} onCancel={() => setConfirm(false)}>
          <p>This makes real model calls on Nebius Token Factory and runs the real simulator on this server. It spends credits: roughly {typical ? usd(typical.c.median) : 'a few cents'} estimated, and takes about {typical ? fmtS(typical.t.median) : 'a few minutes'}.</p>
          <p>It is a <b className="text-text">rehearsal</b>: rehearsal seeds only, never an official result. You can cancel while it runs.</p>
        </Confirm>
      )}

      {source && (
        <div className="mt-8 space-y-6">
          {source.kind === 'replay' ? (
            <div role="note" className="rounded-xl border-2 border-amber bg-amber/10 p-4">
              <div className="mb-2"><SourceChip kind="replay" detail={meta ? `recording of a real live run, ${meta.date}, verdict ${meta.verdict}` : 'recording of a real live run'} /></div>
              <div className="font-display text-lg font-bold text-amber">Recorded replay of a real live rehearsal run{meta ? ` (${meta.date}, verdict ${meta.verdict})` : ''}</div>
              <p className="mt-1 text-sm text-text/90">This is not live. These events were recorded from a real run and are played back{speed > 1 ? ` at ${speed}x, with waits over 2.5 s shortened` : ' in real time'}. Nothing is being computed now.</p>
              <div className="mt-3 flex flex-wrap items-center gap-2 font-mono text-xs">speed
                {[1, 4, 8, 16].map((s) => <button key={s} onClick={() => setSpeed(s)} className={`rounded-full border px-3 py-1 ${speed === s ? 'border-amber bg-amber text-ink' : 'border-white/20 hover:border-amber'}`} aria-pressed={speed === s}>{s}x</button>)}
                <button onClick={() => setReplayKey((k) => k + 1)} className="rounded-full border border-white/20 px-3 py-1 hover:border-amber">restart</button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <span className="chip !border-verm/50 !text-verm"><span className={`h-2 w-2 rounded-full bg-verm ${running ? 'animate-pulse' : ''}`} />{running ? 'LIVE' : view.ended ? 'ENDED' : 'CONNECTING'}</span>
              <SourceChip kind="live" detail="events from this server as they happen" /><span className="font-mono text-xs text-dim">{source.id}{view.masterSeed != null ? ` | master seed ${view.masterSeed}` : ''} | rehearsal</span>
              {running && source.token && <button className="btn btn-ghost !py-1.5 text-sm" onClick={cancel}>Cancel run</button>}
              {running && !source.token && <span className="text-xs text-dim">watching only: you cannot cancel a run you did not start</span>}
            </div>
          )}

          {lost && !view.ended && source.kind === 'live' && (
            <div role="alert" className="rounded-lg border border-verm/40 bg-verm/[.07] p-3 text-sm">Lost the connection to the live server. The run may still be going. <button className="underline" onClick={() => setReplayKey((k) => k + 1)}>Reconnect</button></div>
          )}

          <Timeline stages={view.stages} />
          <div className="grid gap-6 lg:grid-cols-[1.35fr_1fr]">
            <Terminal events={events} />
            <div>
              <h3 className="mb-2 font-display">Gate checks</h3>
              <GateLights gates={view.gates} done={view.ended} />
            </div>
          </div>
          <Candidates attempts={view.attempts} />

          {view.ended && (
            <div className="glass p-6">
              {view.finalStatus === 'finished' && view.verdict ? (
                <>
                  <div className="flex flex-wrap items-center gap-6"><Stamp verdict={view.verdict} />
                    <div className="font-mono text-xs leading-relaxed text-dim">REHEARSAL result, not official.<br />{fmtS(view.elapsedS)} | {view.llmCalls} model calls | {view.tokens.toLocaleString()} tokens<br />estimated cost {usd(view.costUsd)} (estimate; billing not checked)</div></div>
                  {view.metrics && (
                    <div className="mt-5 grid gap-4 md:grid-cols-2">
                      <RatePair title="Analysis set (seen by the fixer)" before={view.metrics.analysis?.before} after={view.metrics.analysis?.after} />
                      <RatePair title="Verification set (rehearsal block)" before={view.metrics.verification?.before} after={view.metrics.verification?.after} target={0.9} />
                    </div>
                  )}
                  {view.strictZero && <p className="mt-3 font-mono text-[11px] text-dim">Strict zero-regression result: {view.strictZero.regressions ?? 'n/a'} regressions ({view.strictZero.pass ? 'would pass' : 'would not pass'}). Held-out after: {pct(view.metrics?.verification?.after?.pass_rate)}</p>}
                </>
              ) : (
                <div role="alert">
                  <div className="font-display text-2xl font-bold text-amber">{view.finalStatus === 'cancelled' ? 'Run cancelled' : view.finalStatus === 'timeout' ? 'Run timed out' : view.finalStatus === 'error' ? 'Run failed to produce a result' : 'No verdict'}</div>
                  <p className="mt-2 text-dim">{view.finalMessage ?? 'The run ended without a verdict.'} No verdict means the fix is neither proven nor disproven; nothing here counts as a pass.</p>
                </div>
              )}
              <div className="mt-6 flex flex-wrap gap-3">
                {view.verdict && <Link to={source.kind === 'live' ? `/live/report/${source.id}` : `/live/report/replay-${source.key}`} className="btn btn-primary">Open full report</Link>}
                <button className="btn btn-ghost" onClick={download}>Download JSON</button>
                <button className="btn btn-ghost" onClick={reset}>Back to the console</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
