import { useEffect, useRef, useState } from 'react'
import { API_BASE } from '../live/api'
import { Skeleton, useToast } from '../motion'
import { SourceChip } from '../ui'

type Row = { group: string; id: string; name: string; stored: string; recomputed: string; status: 'match' | 'mismatch' | 'unverifiable' | 'info'; note: string }
type Resp = { run_id: string; rows: Row[]; integrity: Row[]; limits: Row[]; tally: Record<string, number>; elapsed_s: number; commands: string[]; mode: string }

const MARK: Record<Row['status'], { t: string; c: string; label: string }> = {
  match: { t: 'MATCH', c: '#5be39a', label: 'matches' },
  mismatch: { t: 'MISMATCH', c: '#ff6a47', label: 'does not match' },
  unverifiable: { t: 'CANNOT CHECK', c: '#f2b134', label: 'cannot be checked here' },
  info: { t: 'INFO', c: '#7f8da0', label: 'information' },
}

function Mark({ s }: { s: Row['status'] }) {
  const m = MARK[s]
  return <span className="inline-block whitespace-nowrap rounded-sm px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider" style={{ color: m.c, border: `1px solid ${m.c}66`, background: `${m.c}14` }} aria-label={m.label}>{m.t}</span>
}

function Table({ title, rows }: { title: string; rows: Row[] }) {
  if (!rows.length) return null
  return (
    <div className="glass overflow-x-auto">
      <h3 className="px-4 pt-4 font-display">{title}</h3>
      <table className="mt-2 w-full text-left text-xs sm:min-w-[720px] [&_td]:break-words">
        <thead className="font-mono text-[10px] uppercase tracking-wider text-dim"><tr><th className="px-4 py-2">Check</th><th>Stored</th><th>Recomputed now</th><th /></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id + i} className="border-t hair align-top">
              <td className="px-4 py-2 leading-snug">{r.name}{r.note && <div className="mt-0.5 text-[11px] text-dim">{r.note}</div>}</td>
              <td className="py-2 pr-3 font-mono tick break-all">{r.stored || '-'}</td>
              <td className="py-2 pr-3 font-mono tick break-all">{r.recomputed || '-'}</td>
              <td className="py-2 pr-3"><Mark s={r.status} /></td>
            </tr>))}
        </tbody>
      </table>
    </div>
  )
}

/** Recomputes and re-simulates (analysis set only) one recorded official run on the server, then shows stored vs recomputed numbers. */
export default function VerifyPanel({ runId }: { runId: string }) {
  const toast = useToast()
  const [state, setState] = useState<'idle' | 'running' | 'done' | 'offline' | 'error'>('idle')
  const [res, setRes] = useState<Resp | null>(null)
  const [msg, setMsg] = useState('')
  const [secs, setSecs] = useState(0)
  const [clientS, setClientS] = useState<number | null>(null)
  const timer = useRef<ReturnType<typeof setInterval>>()
  useEffect(() => () => clearInterval(timer.current), [])
  const cmd = `scripts/dock.sh python scripts/verify_official.py --run ${runId}`

  const run = async () => {
    setState('running'); setRes(null); setSecs(0); setClientS(null)
    const t0 = performance.now()
    timer.current = setInterval(() => setSecs(Math.round((performance.now() - t0) / 1000)), 500)
    try {
      const ctl = new AbortController()
      const kill = setTimeout(() => ctl.abort(), 150000)
      const r = await fetch(`${API_BASE}/api/verify/${encodeURIComponent(runId)}`, { method: 'POST', signal: ctl.signal })
      clearTimeout(kill)
      const b = await r.json().catch(() => null)
      clearInterval(timer.current)
      setClientS(Math.round((performance.now() - t0) / 100) / 10)
      if (r.ok && b && Array.isArray(b.rows)) { setRes(b); setState('done'); return }
      if (b && b.message) { setMsg(b.message); setState('error'); return }
      setState('offline')
    } catch { clearInterval(timer.current); setState('offline') }
  }

  const rows = res?.rows ?? []
  const t = res?.tally
  return (
    <section className="mb-14" aria-label="Verify this result">
      <div className="eyebrow mb-1.5">don't trust it, check it</div>
      <h2 className="mb-3 text-3xl">Verify this result</h2>
      <p className="max-w-3xl text-sm leading-relaxed text-dim">
        This button asks the backend to recompute this run's gate numbers from the stored counts, <b className="text-text">re-simulate the run's analysis set now</b> (the unpatched policy and the selected patch, with the stored scenarios and seeds)
        and compare every number with what was stored. Held-out seeds are never simulated: only the gate may use them, so held-out counts are checked for internal consistency only.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button className="btn btn-primary disabled:opacity-60" onClick={run} disabled={state === 'running'}>{state === 'running' ? `Verifying... ${secs}s` : state === 'done' ? 'Verify again' : 'Verify this result'}</button>
        <SourceChip kind="live" detail="computed on this server when you press the button | no model calls, no credits" />
      </div>
      {state === 'running' && <div className="mt-4"><Skeleton className="h-24" /><p className="mt-2 font-mono text-[11px] text-dim" role="status">re-simulating about 500 scenarios and checking the ledger... {secs}s elapsed</p></div>}
      {state === 'offline' && (
        <div className="mt-4 rounded-xl border border-amber/40 bg-amber/[.07] p-4 text-sm" role="alert">
          <b className="text-amber">Backend offline.</b> Nothing was verified, and no result is shown. Run the same check yourself in a terminal from the repository root:
          <pre className="mt-2 overflow-x-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-text">{cmd}</pre>
          <button className="chip mt-2 hover:!border-amber/60 hover:!text-text" onClick={() => navigator.clipboard?.writeText(cmd).then(() => toast('Command copied.', 'ok'))}>Copy command</button>
        </div>
      )}
      {state === 'error' && <div className="mt-4 rounded-xl border border-verm/40 bg-verm/[.07] p-4 text-sm" role="alert"><b className="text-verm">Could not verify.</b> {msg}</div>}
      {state === 'done' && res && t && (
        <div className="mt-5 space-y-5">
          <div className={`rounded-xl border p-4 ${t.mismatch ? 'border-verm/50 bg-verm/[.07]' : 'border-phos/40 bg-phos/[.06]'}`} role="status">
            <div className="font-display text-xl font-semibold">{t.mismatch ? `${t.mismatch} mismatch${t.mismatch > 1 ? 'es' : ''} found` : 'Every check that could run matches'}</div>
            <p className="mt-1 font-mono text-xs text-dim">{t.match} match | {t.mismatch} mismatch | {t.unverifiable} cannot be checked in this environment | computed just now on the server in {res.elapsed_s} s (page waited {clientS} s)</p>
          </div>
          <Table title="Recomputed from the stored numbers (gate statuses, Wilson intervals, verdict)" rows={rows.filter((r) => r.group === 'recompute')} />
          <Table title="Re-simulated now: analysis set, unpatched policy and selected patch" rows={rows.filter((r) => r.group === 'resimulate')} />
          <Table title="Integrity: held-out blocks, ledger, protocol before the run, frozen pipeline" rows={res.integrity} />
          <Table title="What cannot be re-verified, and why" rows={res.limits} />
          <p className="font-mono text-[11px] text-dim">Same checks in a terminal: <span className="text-text">{res.commands[0]}</span> (all five runs: <span className="text-text">{res.commands[1]}</span>)</p>
        </div>
      )}
    </section>
  )
}
