import { ReactNode, Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Hyp, Rate, pct, useData, usd } from '../lib'
import { Skeleton, useMotionPrefs, usePageTitle } from '../motion'
import { RatePair } from '../ui'
import { HypCard } from './Run'
import { Confirm } from '../live/parts'
import { PgError, ParamSpec, Spec, errTitle, fetchSpec, post } from '../play/api'
import type { Traj } from '../play/Replay3D'
import type { ScenData } from '../three/FailureMap3D'

const Player = lazy(() => import('../play/Replay3D'))
const Map3D = lazy(() => import('../three/FailureMap3D'))

type Vals = Record<string, number>
type Result = { scenario_id: string; seed: number; success: boolean; collision: boolean; completion_time_s: number; final_place_error_m: number; max_slip_m: number; failure_reason: string | null }
type ScenResp = Traj & { result: Result; explanation: string; scenario: Vals; policy: Vals; seed: number; wall_clock_s?: number }
type Metrics = Rate & { passes: number; failure_reasons: Record<string, number> }
type Rows = { ids: string[]; ok: number[]; reason: (string | null)[]; default_ok: number[]; default_reason: (string | null)[]; seed: number[] } & Record<string, any>
type SweepResp = { sweep_id: string; n: number; seed: number; policy: Vals; metrics: Metrics; default_metrics: Metrics; evidence_bins: { axis: string; range: number[]; n: number; n_fail: number; fail_rate: number }[]; rows: Rows; wall_clock_s: number }
type Example = ScenResp & { label: string; why: string }
type Interp = { unsupported: boolean; reason: string | null; parameters: Record<string, { value: number; reason: string; clamped: boolean; rounded: boolean }> | null; model?: string; latency_s?: number; estimated_cost_usd?: number | null; label?: string }
type Analysis = { hypotheses: Hyp[]; model: string; estimated_cost_usd: number | null; label: string; cost_note: string }

const AXIS_KEYS = ['mass_kg', 'friction', 'size_m', 'pos_offset_x', 'pos_offset_y', 'sensor_noise_m', 'gripper_delay_steps']
const bad = (p: ParamSpec, v: number) => !Number.isFinite(v) || v < p.min || v > p.max || (p.integer && !Number.isInteger(v))
const fmtN = (x: number, d = 3) => (Math.abs(x) >= 100 ? x.toFixed(0) : Number(x.toPrecision(d)).toString())
const REASON: Record<string, string> = { MISSED_GRASP: 'missed grasp', SLIPPED_ON_LIFT: 'slipped on lift', DROPPED_IN_TRANSIT: 'dropped in transit', COLLISION: 'collision', PLACED_OUTSIDE_ZONE: 'placed outside zone', TIMEOUT: 'timeout' }

function Notice({ tone, title, children }: { tone: 'warn' | 'err' | 'info'; title?: string; children: ReactNode }) {
  const c = tone === 'err' ? 'border-verm/40 bg-verm/[.07]' : tone === 'warn' ? 'border-amber/40 bg-amber/[.07]' : 'border-white/15 bg-white/[.03]'
  return <div role={tone === 'info' ? 'note' : 'alert'} className={`rounded-xl border p-3 text-sm leading-relaxed ${c}`}>{title && <b className={tone === 'err' ? 'text-verm' : 'text-amber'}>{title}. </b>}{children}</div>
}

function Outcome({ ok }: { ok: boolean }) {
  const c = ok ? '#5be39a' : '#ff6a47'
  return (
    <span className="stamp-in inline-block select-none rounded-md font-display text-3xl font-bold leading-none" style={{ color: c, border: `3px solid ${c}`, padding: '.35rem .9rem', background: `${c}0d`, transform: 'rotate(-4deg)' }}>
      {ok ? 'PASS' : 'FAIL'}
    </span>
  )
}

function ParamControl({ p, v, set, off }: { p: ParamSpec; v: number; set: (x: number) => void; off?: boolean }) {
  const inv = bad(p, v)
  const step = p.integer ? 1 : (p.max - p.min) / 200
  return (
    <div className={`py-2 ${off ? 'opacity-45' : ''}`} title={off ? (p.note ?? '') : p.help}>
      <div className="flex items-baseline justify-between gap-2 text-sm"><label htmlFor={`pg-${p.name}`} className="font-medium">{p.label}</label><span className="font-mono text-[10px] text-dim">{fmtN(p.min)} to {fmtN(p.max)} {p.unit}</span></div>
      <div className="mt-1 flex items-center gap-3">
        <input type="range" min={p.min} max={p.max} step={step} value={Number.isFinite(v) ? Math.min(Math.max(v, p.min), p.max) : p.min} disabled={off} onChange={(e) => set(p.integer ? Math.round(+e.target.value) : +e.target.value)}
          className="min-w-0 flex-1 accent-[#f2b134]" aria-label={`${p.label} slider`} />
        <input id={`pg-${p.name}`} type="number" inputMode="decimal" step={p.integer ? 1 : 'any'} min={p.min} max={p.max} value={Number.isFinite(v) ? v : ''} disabled={off}
          onChange={(e) => set(e.target.value === '' ? NaN : +e.target.value)} aria-invalid={inv}
          className={`w-24 rounded-lg border bg-black/40 px-2 py-1 text-right font-mono text-xs outline-none focus:border-amber ${inv ? 'border-verm' : 'border-white/15'}`} />
      </div>
      {inv && !off && <p className="mt-1 text-xs text-verm">Must be {p.integer ? 'a whole number ' : ''}between {fmtN(p.min)} and {fmtN(p.max)}.</p>}
      {off && <p className="mt-1 text-[11px] text-dim">Measured no effect: not tunable.</p>}
    </div>
  )
}

function Metric({ k, v, tone }: { k: string; v: ReactNode; tone?: string }) {
  return <div className="rounded-lg border hair bg-white/[.02] p-3"><div className="text-[11px] text-dim">{k}</div><div className={`font-mono text-sm tick ${tone ?? ''}`}>{v}</div></div>
}

function SingleResult({ r, label }: { r: ScenResp; label?: string }) {
  const { reduce } = useMotionPrefs()
  const x = r.result
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-5">
        <Outcome ok={x.success} />
        <div className="text-sm text-dim">{label && <div className="font-medium text-text">{label}</div>}seed {r.seed} | {r.wall_clock_s != null ? `simulated in ${r.wall_clock_s} s` : 'recorded real run'}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Metric k="Success" v={x.success ? 'yes' : 'no'} tone={x.success ? 'text-phos' : 'text-verm'} />
        <Metric k="Collision" v={x.collision ? 'yes' : 'no'} tone={x.collision ? 'text-verm' : ''} />
        <Metric k="Completion time" v={`${x.completion_time_s.toFixed(2)} s`} />
        <Metric k="Final place error" v={`${(x.final_place_error_m * 100).toFixed(1)} cm`} />
        <Metric k="Max slip" v={`${(x.max_slip_m * 100).toFixed(1)} cm`} />
        <Metric k="Failure reason" v={x.failure_reason ? (REASON[x.failure_reason] ?? x.failure_reason) : 'none'} tone={x.failure_reason ? 'text-verm' : ''} />
      </div>
      <p className="text-sm leading-relaxed text-dim">{r.explanation}</p>
      <Suspense fallback={<Skeleton className="h-[400px]" />}><Player data={r} reduce={reduce} /></Suspense>
    </div>
  )
}

function AxisBins({ bins }: { bins: SweepResp['evidence_bins'] }) {
  const axes = [...new Set(bins.map((b) => b.axis))]
  const name: Record<string, string> = { mass_kg: 'mass', friction: 'friction', size_m: 'size', pos_offset_x: 'offset x', pos_offset_y: 'offset y', sensor_noise_m: 'sensor noise', gripper_delay_steps: 'gripper delay' }
  return (
    <div className="glass p-4" role="img" aria-label="Failure rate by parameter range">
      <h3 className="mb-3 font-display">Failure rate by parameter range</h3>
      <div className="space-y-1.5">
        {axes.map((ax) => (
          <div key={ax} className="flex items-center gap-2">
            <span className="w-24 shrink-0 text-xs text-dim">{name[ax] ?? ax}</span>
            <div className="grid flex-1 grid-cols-5 gap-1">
              {bins.filter((b) => b.axis === ax).map((b, i) => (
                <div key={i} title={`${name[ax] ?? ax} ${fmtN(b.range[0])} to ${fmtN(b.range[1])}: ${b.n_fail} of ${b.n} fail`} className="rounded-sm py-1 text-center font-mono text-[10px] text-white/90"
                  style={{ background: b.n ? `rgba(255,106,71,${0.1 + 0.85 * b.fail_rate})` : 'rgba(255,255,255,.04)' }}>{b.n ? `${Math.round(b.fail_rate * 100)}%` : '-'}</div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-2 font-mono text-[10.5px] text-dim">each row: five equal bins from the axis minimum to its maximum; cell = share of this policy's scenarios that fail there (from the evidence code)</p>
    </div>
  )
}

function Reasons({ m, d }: { m: Metrics; d: Metrics }) {
  const keys = [...new Set([...Object.keys(m.failure_reasons), ...Object.keys(d.failure_reasons)])]
  if (!keys.length) return <p className="glass p-4 text-sm text-dim">No failures in either run.</p>
  return (
    <div className="glass overflow-x-auto p-4">
      <h3 className="mb-2 font-display">Failure reasons</h3>
      <table className="w-full min-w-[320px] text-left text-sm"><thead className="font-mono text-[11px] text-dim"><tr><th className="py-1">reason</th><th>default policy</th><th>this policy</th></tr></thead>
        <tbody>{keys.map((k) => <tr key={k} className="border-t hair"><td className="py-1.5">{REASON[k] ?? k}</td><td className="font-mono">{d.failure_reasons[k] ?? 0}</td><td className="font-mono">{m.failure_reasons[k] ?? 0}</td></tr>)}</tbody></table>
    </div>
  )
}

export default function Playground() {
  usePageTitle('Playground')
  const { reduce } = useMotionPrefs()
  const [spec, setSpec] = useState<Spec | null | undefined>(undefined)
  const examples = useData<Example[]>('playground_examples.json')
  const [tab, setTab] = useState<'single' | 'sweep'>('single')
  const [scn, setScn] = useState<Vals>({})
  const [pol, setPol] = useState<Vals>({})
  const [seed, setSeed] = useState<string>('')
  const [n, setN] = useState(100)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<PgError | null>(null)
  const [single, setSingle] = useState<ScenResp | null>(null)
  const [sweep, setSweep] = useState<SweepResp | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [code, setCode] = useState('')
  const [desc, setDesc] = useState('')
  const [interp, setInterp] = useState<Interp | null>(null)
  const [interpBusy, setInterpBusy] = useState(false)
  const [interpErr, setInterpErr] = useState<PgError | null>(null)

  useEffect(() => { fetchSpec().then(setSpec) }, [])
  useEffect(() => {
    if (!spec) return
    const b = spec.presets.find((p) => p.id === 'benign')!
    setScn({ ...(b.scenario as Vals) })
    setPol(Object.fromEntries(spec.policy.map((p) => [p.name, p.default as number])))
  }, [spec])

  const online = !!spec && spec.enabled
  const invalid = useMemo(() => !spec ? false : spec.scenario.some((p) => bad(p, scn[p.name])) || spec.policy.some((p) => bad(p, pol[p.name])) || (seed !== '' && (!Number.isInteger(+seed) || +seed < spec.seed.min || +seed > spec.seed.max)), [spec, scn, pol, seed])
  const polInvalid = useMemo(() => !spec ? false : spec.policy.some((p) => bad(p, pol[p.name])) || (seed !== '' && (!Number.isInteger(+seed) || +seed < spec.seed.min || +seed > spec.seed.max)), [spec, pol, seed])
  const applyPreset = (id: string) => {
    const p = spec?.presets.find((x) => x.id === id)
    if (!p) return
    if (p.scenario) setScn({ ...p.scenario })
    if (p.policy) setPol({ ...p.policy })
  }

  const runSingle = useCallback(async (s: Vals, p: Vals, sd?: number) => {
    setBusy(true); setErr(null)
    const r = await post<ScenResp>('/api/sim/scenario', { scenario: s, policy: p, ...(sd != null ? { seed: sd } : {}) }, 30000)
    setBusy(false)
    if (r.ok) setSingle(r.data); else setErr(r.error)
  }, [])
  const runSweep = async () => {
    setBusy(true); setErr(null); setAnalysis(null)
    const r = await post<SweepResp>('/api/sim/sweep', { policy: pol, n, ...(seed !== '' ? { seed: +seed } : {}) }, 90000)
    setBusy(false)
    if (r.ok) setSweep(r.data); else setErr(r.error)
  }
  const doAnalyze = async () => {
    if (!sweep) return
    setConfirm(false); setBusy(true); setErr(null)
    const r = await post<Analysis>('/api/sim/analyze', { sweep_id: sweep.sweep_id, ...(code ? { access_code: code } : {}) }, 180000)
    setBusy(false)
    if (r.ok) setAnalysis(r.data); else setErr(r.error)
  }
  const doInterpret = async () => {
    setInterpBusy(true); setInterpErr(null); setInterp(null)
    const r = await post<Interp>('/api/sim/interpret', { text: desc, ...(code ? { access_code: code } : {}) }, 90000)
    setInterpBusy(false)
    if (!r.ok) { setInterpErr(r.error); return }
    setInterp(r.data)
    if (!r.data.unsupported && r.data.parameters) setScn(Object.fromEntries(Object.entries(r.data.parameters).map(([k, g]) => [k, g.value])))
  }
  const pick = (i: number) => {
    if (!sweep || !spec) return
    const s: Vals = Object.fromEntries(AXIS_KEYS.map((k) => [k, sweep.rows[k][i]]))
    setScn(s); setPol({ ...sweep.policy }); setSeed(String(sweep.rows.seed[i])); setTab('single'); setSingle(null)
    runSingle(s, sweep.policy, sweep.rows.seed[i])
  }
  const mapData: ScenData | null = useMemo(() => !sweep ? null : ({ set: `playground sweep (seed ${sweep.seed})`, policy: 'this policy', n: sweep.n, ids: sweep.rows.ids, tag: sweep.rows.ids.map(() => null), ok: sweep.rows.ok, reason: sweep.rows.reason,
    mass_kg: sweep.rows.mass_kg, friction: sweep.rows.friction, size_m: sweep.rows.size_m, sensor_noise_m: sweep.rows.sensor_noise_m, gripper_delay_steps: sweep.rows.gripper_delay_steps, pos_offset_x: sweep.rows.pos_offset_x, pos_offset_y: sweep.rows.pos_offset_y }), [sweep])

  return (
    <div>
      <div className="eyebrow mb-3">playground</div>
      <h1>Try your own scenario and policy.</h1>
      <p className="mt-3 max-w-2xl text-lg text-dim">Set the cube and the sensor conditions, set the policy parameters, and get real results from the same simulator the pipeline uses.</p>
      <div className="mt-4"><Notice tone="warn" title="Exploration, not a gate verdict">Uses the frozen simulator and parameter ranges. Not part of the official evaluation. One task only: a gripper picks up a cube, carries it over a low wall and places it in a target zone. Other robots would need a new simulator and a recalibrated gate (future work).</Notice></div>

      {spec === undefined && <div className="mt-8 grid gap-6 lg:grid-cols-[380px_1fr]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div>}

      {spec !== undefined && !online && (
        <div className="mt-8 space-y-6">
          <Notice tone="info" title={spec ? 'The playground is switched off on this server' : 'Playground backend offline'}>
            <b className="text-text">Recorded examples; the interactive playground needs the backend.</b> The three results below are real runs of the frozen simulator that were recorded earlier. They are not live.
          </Notice>
          {!examples.data ? <Skeleton className="h-96" /> : examples.data.map((e) => (
            <section key={e.label} className="glass p-5">
              <h2 className="mb-1 text-2xl">{e.label}</h2><p className="mb-4 text-sm text-dim">{e.why} (recorded example)</p>
              <SingleResult r={e} />
            </section>
          ))}
        </div>
      )}

      {online && spec && spec.interpret_available && tab === 'single' && (
        <section className="glass mt-6 p-5" aria-label="Describe the situation in plain English">
          <h2 className="text-xl">Describe the situation in plain English</h2>
          <p className="mt-1 text-sm text-dim">A Nemotron model proposes values for the scenario sliders. It only proposes: nothing runs until you press Run simulation, and the simulator decides the outcome.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {['A 700 g cube on a wet tray with a noisy camera', 'A tiny cube on a dry rubber mat and a laggy gripper', 'A heavy cube that sits a bit off-centre, clean sensor'].map((t) => <button key={t} className="chip hover:!border-amber/60 hover:!text-text" onClick={() => setDesc(t)}>{t}</button>)}
          </div>
          <textarea value={desc} maxLength={spec.interpret_max_chars ?? 300} onChange={(e) => setDesc(e.target.value)} rows={2} placeholder="e.g. a 700 g cube on a wet tray with a noisy camera" aria-label="Situation description"
            className="mt-3 block w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 text-sm outline-none focus:border-amber" />
          <div className="mt-2 flex flex-wrap items-center gap-3">
            {spec.analyze_access_code_required && <input type="password" value={code} onChange={(e) => setCode(e.target.value)} placeholder="access code" aria-label="Access code" className="w-36 rounded-lg border border-white/15 bg-black/40 px-3 py-1.5 font-mono text-xs outline-none focus:border-amber" />}
            <button className="btn btn-ghost !py-2" disabled={interpBusy || !desc.trim()} onClick={doInterpret}>{interpBusy ? 'Interpreting...' : 'Interpret'}</button>
            <span className="font-mono text-[11px] text-dim">{desc.length}/{spec.interpret_max_chars ?? 300} | about {usd(spec.interpret_est_usd)} per call (estimate)</span>
          </div>
          {interpErr && <div className="mt-3"><Notice tone="err" title={errTitle[interpErr.kind]}>{interpErr.message}</Notice></div>}
          {interp?.unsupported && <div className="mt-3"><Notice tone="warn" title="Not something the simulator covers">The simulator covers only the cube pick-and-place task. {interp.reason}</Notice></div>}
          {interp && !interp.unsupported && interp.parameters && (
            <div className="mt-4">
              <Notice tone="warn" title="Model interpretation, unverified">Edit before running. The sliders below have been filled in. {interp.model ? `Model: ${interp.model.split('/').pop()}, ${interp.latency_s}s, estimated cost ${usd(interp.estimated_cost_usd)}.` : ''}</Notice>
              <ul className="mt-3 grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                {spec.scenario.map((p) => { const g = interp.parameters![p.name]; return g ? (
                  <li key={p.name} className="flex gap-2"><span className="w-36 shrink-0 font-medium">{p.label}</span><span className="font-mono text-xs tick">{fmtN(g.value)} {p.unit}</span>
                    <span className="min-w-0 text-xs text-dim">{g.reason}{g.clamped ? ' (clamped to the allowed range)' : ''}{g.rounded ? ' (rounded to a whole number)' : ''}</span></li>) : null })}
              </ul>
            </div>
          )}
        </section>
      )}

      {online && spec && (
        <div className="mt-8 grid gap-6 lg:grid-cols-[400px_1fr]">
          <div className="glass h-fit p-5 lg:sticky lg:top-24">
            <div role="tablist" className="mb-4 flex overflow-hidden rounded-full border border-white/15 text-sm">
              {(['single', 'sweep'] as const).map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => { setTab(t); setErr(null) }} className={`flex-1 px-3 py-2 font-medium ${tab === t ? 'bg-amber text-ink' : 'text-dim hover:text-text'}`}>{t === 'single' ? 'Single scenario' : 'Sweep'}</button>)}
            </div>
            <div className="mb-3 flex flex-wrap gap-2" aria-label="Presets">
              {spec.presets.filter((p) => tab === 'single' || !p.scenario).map((p) => <button key={p.id} className="chip hover:!border-amber/60 hover:!text-text" onClick={() => applyPreset(p.id)}>{p.label}</button>)}
            </div>
            {tab === 'single' ? (
              <>
                <h3 className="mt-3 text-sm text-amber">Scenario conditions</h3>
                {spec.scenario.map((p) => <ParamControl key={p.name} p={p} v={scn[p.name]} set={(x) => setScn((s) => ({ ...s, [p.name]: x }))} />)}
              </>
            ) : <Notice tone="info">A sweep samples scenario conditions across the full frozen ranges (a seeded Latin-hypercube coverage sweep), then runs your policy and the default policy on the same scenarios.</Notice>}
            <h3 className="mt-4 text-sm text-amber">Policy parameters</h3>
            {spec.policy.map((p) => <ParamControl key={p.name} p={p} v={pol[p.name]} off={!p.tunable} set={(x) => setPol((s) => ({ ...s, [p.name]: x }))} />)}
            <label className="mt-2 block text-sm">Seed (optional)<input value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={String(spec.seed.default)} inputMode="numeric"
              className="mt-1 block w-full rounded-lg border border-white/15 bg-black/40 px-3 py-1.5 font-mono text-xs outline-none focus:border-amber" /></label>
            <p className="mt-1 text-[11px] text-dim">Playground seeds are {spec.seed.min} to {spec.seed.max}; held-out and rehearsal seeds are never accepted.</p>
            {tab === 'sweep' && (
              <div className="mt-3"><label className="flex items-baseline justify-between text-sm"><span className="font-medium">Scenarios in the sweep</span><span className="font-mono text-xs">{n}</span></label>
                <input type="range" min={10} max={spec.max_sweep_n} step={10} value={n} onChange={(e) => setN(+e.target.value)} className="w-full accent-[#f2b134]" aria-label="Number of scenarios" /></div>
            )}
            <button className="btn btn-primary mt-5 w-full justify-center disabled:opacity-50" disabled={busy || (tab === 'single' ? invalid : polInvalid)}
              onClick={() => (tab === 'single' ? runSingle(scn, pol, seed !== '' ? +seed : undefined) : runSweep())}>
              {busy ? 'Simulating...' : tab === 'single' ? 'Run simulation' : `Test this policy on ${n} scenarios`}
            </button>
          </div>

          <div className="min-w-0 space-y-6">
            {err && <Notice tone="err" title={errTitle[err.kind]}>{err.message}{err.kind === 'busy' || err.kind === 'rate' ? ' Try again shortly.' : ''}</Notice>}
            {busy && <div className="glass p-5" role="status"><div className="flex items-center gap-3"><span className="h-3 w-3 animate-pulse rounded-full bg-amber" /><span className="text-sm">{tab === 'sweep' ? `Running ${n} scenarios for your policy and for the default policy (about ${Math.max(3, Math.round(n / 8))} to ${Math.max(6, Math.round(n / 4))} s)...` : 'Running the simulation...'}</span></div>{!reduce && <div className="mt-3 h-1.5 overflow-hidden rounded bg-white/10"><div className="h-full w-1/3 animate-shimmer rounded bg-amber/70" /></div>}</div>}

            {tab === 'single' && (single ? <div className="glass p-5"><SingleResult r={single} /></div> : !busy && <div className="glass p-8 text-center text-dim">Press <b className="text-text">Run simulation</b> to simulate one pick-and-place with these settings.</div>)}

            {tab === 'sweep' && (sweep ? (
              <div className="space-y-5">
                <div className="glass p-5">
                  <h2 className="mb-1 text-2xl">Your policy vs the default policy</h2>
                  <p className="mb-4 text-sm text-dim">{sweep.n} scenarios (seed {sweep.seed}), same scenarios for both policies, simulated in {sweep.wall_clock_s} s. Exploration, not a gate verdict.</p>
                  <RatePair title="Pass rate (Wilson 95% interval)" before={sweep.default_metrics} after={sweep.metrics} beforeLabel="default" afterLabel="yours" />
                  <p className="mt-2 font-mono text-[11px] text-dim">{sweep.metrics.passes} of {sweep.metrics.n} pass with your policy; {sweep.default_metrics.passes} of {sweep.default_metrics.n} with the default.</p>
                </div>
                <div className="grid gap-5 md:grid-cols-2"><Reasons m={sweep.metrics} d={sweep.default_metrics} /><AxisBins bins={sweep.evidence_bins} /></div>
                {mapData && !reduce && (
                  <div className="glass p-5"><h2 className="mb-3 text-2xl">Failure map of this sweep</h2>
                    <Suspense fallback={<Skeleton className="h-[440px]" />}>
                      <Map3D d={mapData} reduce={reduce} alt={{ ok: sweep.rows.default_ok, reason: sweep.rows.default_reason, label: 'default policy', main: 'your policy' }} onPick={pick} pickHint="click a point to replay that scenario" />
                    </Suspense></div>
                )}
                {spec.analyze_available && (
                  <div className="glass p-5">
                    <h2 className="mb-2 text-2xl">Analyze with Nemotron</h2>
                    <p className="mb-3 text-sm text-dim">Asks a Nemotron reasoning model for testable hypotheses about the failures. This spends Nebius credits (about {usd(spec.analyze_est_usd)} estimated) and is never run automatically.</p>
                    <button className="btn btn-ghost" disabled={busy || sweep.metrics.n - sweep.metrics.passes < 5} onClick={() => setConfirm(true)}>Analyze with Nemotron</button>
                    {sweep.metrics.n - sweep.metrics.passes < 5 && <span className="ml-3 text-xs text-dim">Needs at least 5 failures.</span>}
                    {analysis && (
                      <div className="mt-5 space-y-4"><Notice tone="warn" title="Model opinion, unverified">{analysis.label} Estimated cost {usd(analysis.estimated_cost_usd)} ({analysis.cost_note})</Notice>
                        <div className="grid gap-4 md:grid-cols-2">{analysis.hypotheses.map((h) => <HypCard key={h.id} h={h} />)}</div></div>
                    )}
                  </div>
                )}
              </div>
            ) : !busy && <div className="glass p-8 text-center text-dim">Press <b className="text-text">Test this policy</b> to run your parameters and the default policy on the same scenarios.</div>)}
          </div>
        </div>
      )}

      {confirm && spec && (
        <Confirm title="Analyze this sweep with Nemotron?" confirm="Yes, spend the credits" onConfirm={doAnalyze} onCancel={() => setConfirm(false)}>
          <p>This calls a Nemotron reasoning model on Nebius Token Factory with the sweep's failure statistics. Estimated cost about {usd(spec.analyze_est_usd)} (an estimate from token counts; billing is not checked), counted against the daily spend cap.</p>
          {spec.analyze_access_code_required && <label className="block">Access code<input type="password" value={code} onChange={(e) => setCode(e.target.value)} className="mt-1 block w-full rounded-lg border border-white/15 bg-black/40 px-3 py-2 font-mono text-sm outline-none focus:border-amber" /></label>}
          <p>The answer is the model's opinion and is labelled unverified; every number shown comes from the sweep's evidence.</p>
        </Confirm>
      )}
    </div>
  )
}
