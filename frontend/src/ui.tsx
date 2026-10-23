import { ReactNode } from 'react'
import { Badges, Check, Heat, Rate, Status, ci, pct } from './lib'
import { Reveal } from './motion'

export const verdictColor = (v: string | null) => (v === 'VERIFIED' ? '#5be39a' : v === 'FAILED' ? '#ff6a47' : v === 'UNVERIFIED' ? '#f2b134' : '#7f8da0')

/** A rubber-stamp style verdict mark. */
export function Stamp({ verdict, size = 'lg' }: { verdict: string | null; size?: 'sm' | 'lg' }) {
  const c = verdictColor(verdict)
  const big = size === 'lg'
  return (
    <span className="stamp-in inline-block select-none font-display font-black uppercase leading-none tracking-wider"
      style={{ color: c, border: `${big ? 4 : 2}px solid ${c}`, padding: big ? '.3rem .9rem' : '.1rem .5rem', fontSize: big ? '2.6rem' : '1rem',
        borderRadius: 6, boxShadow: `inset 0 0 0 2px rgba(0,0,0,.35), 0 0 34px ${c}33`, background: `${c}0d`, transform: 'rotate(-4deg)' }}>
      {verdict ?? 'NO VERDICT'}
    </span>
  )
}

const STATUS: Record<Status, { label: string; color: string; hint: string }> = {
  pass: { label: 'PASS', color: '#5be39a', hint: 'The check ran and passed.' },
  fail: { label: 'FAIL', color: '#ff6a47', hint: 'The check ran and did not pass.' },
  not_run: { label: 'NOT RUN', color: '#f2b134', hint: 'The check could not run (missing or incomplete data). This makes a verdict UNVERIFIED.' },
  skipped_after_failure: { label: 'SKIPPED', color: '#7f8da0', hint: 'Deliberately not run because an earlier check already failed (the single-use held-out block is not spent).' },
}
export function Chip({ status }: { status: Status }) {
  const s = STATUS[status]
  return (
    <span title={s.hint} className="inline-block rounded-sm px-2 py-0.5 font-mono text-[11px] font-semibold tracking-widest"
      style={{ color: s.color, border: `1px solid ${s.color}66`, background: `${s.color}14` }}>{s.label}</span>
  )
}

export function BadgeRow({ b }: { b: Badges }) {
  const items: [string, string, string][] = [
    [`PIPELINE ${b.pipeline_version.toUpperCase()}`, '#7f8da0', b.pipeline_version === 'v2' ? 'Frozen as git tag pipeline-frozen-v2' : 'Superseded pipeline v1 (tag pipeline-frozen)'],
    [b.mode === 'official' ? 'OFFICIAL' : 'REHEARSAL', b.mode === 'official' ? '#f2b134' : '#7f8da0',
      b.mode === 'official' ? 'Pre-registered batch on single-use held-out seeds' : 'Verification used the rehearsal seed block: not an official result'],
    [`RUNNER: ${b.runner.toUpperCase()}`, '#ff6a47', 'Simulations ran in a local container, not on Nebius Serverless Jobs'],
    [b.recorded ? 'RECORDED REAL RUN' : 'LIVE', '#5be39a', 'Replayed from stored artifacts of a real run; nothing is computed in this page'],
  ]
  return (
    <div className="flex flex-wrap gap-2">
      {items.map(([t, c, h]) => (
        <span key={t} title={h} className="rounded-sm px-2 py-0.5 font-mono text-[10.5px] font-medium tracking-wider" style={{ color: c, border: `1px solid ${c}55` }}>{t}</span>
      ))}
    </div>
  )
}

export function Section({ id, kicker, title, children, delay = 0 }: { id?: string; kicker?: string; title: string; children: ReactNode; delay?: number }) {
  return (
    <Reveal className="mb-14 scroll-mt-24" delay={delay / 1000}>
      <section id={id}>
        {kicker && <div className="eyebrow mb-1.5">{kicker}</div>}
        <h2 className="mb-5 font-display text-3xl font-extrabold text-text md:text-4xl">{title}</h2>
        {children}
      </section>
    </Reveal>
  )
}

export function Note({ children, tone = 'dim' }: { children: ReactNode; tone?: 'dim' | 'warn' }) {
  return <p className={`text-sm leading-relaxed ${tone === 'warn' ? 'border-l-2 border-amber pl-3 text-text' : 'text-dim'}`}>{children}</p>
}

/** Horizontal interval plot (dot = estimate, whisker = Wilson 95% interval) on a 0 to 100% axis. */
export function IntervalPlot({ items }: { items: { label: string; sub: string; k: number; n: number; lo: number; hi: number }[] }) {
  const W = 560, L = 150, R = 20
  const x = (v: number) => L + (W - L - R) * v
  return (
    <svg viewBox={`0 0 ${W} ${items.length * 54 + 34}`} className="w-full" role="img" aria-label="VERIFIED rate with Wilson 95% intervals">
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={6} y2={items.length * 54 + 6} stroke="#1f2924" />
          <text x={x(t)} y={items.length * 54 + 24} textAnchor="middle" fill="#8b998f" fontSize="11" fontFamily="JetBrains Mono">{Math.round(t * 100)}%</text>
        </g>
      ))}
      {items.map((it, i) => {
        const y = 30 + i * 54, r = it.k / it.n
        return (
          <g key={it.label}>
            <text x={0} y={y - 4} fill="#d8dfd4" fontSize="13" fontFamily="Instrument Sans" fontWeight="600">{it.label}</text>
            <text x={0} y={y + 12} fill="#8b998f" fontSize="11" fontFamily="JetBrains Mono">{it.sub}</text>
            <line x1={x(it.lo)} x2={x(it.hi)} y1={y} y2={y} stroke="#f2b134" strokeWidth="3" strokeLinecap="round" className="grow" />
            <line x1={x(it.lo)} x2={x(it.lo)} y1={y - 7} y2={y + 7} stroke="#f2b134" strokeWidth="2" />
            <line x1={x(it.hi)} x2={x(it.hi)} y1={y - 7} y2={y + 7} stroke="#f2b134" strokeWidth="2" />
            <circle cx={x(r)} cy={y} r="6" fill="#090b0a" stroke="#5be39a" strokeWidth="3" />
            <text x={x(r)} y={y - 12} textAnchor="middle" fill="#5be39a" fontSize="11" fontFamily="JetBrains Mono" fontWeight="600">{it.k}/{it.n}</text>
          </g>
        )
      })}
    </svg>
  )
}

/** Before and after pass rate with Wilson 95% whiskers on a 0 to 100% axis. */
export function RatePair({ title, before, after, target }: { title: string; before?: Rate | null; after?: Rate | null; target?: number }) {
  const row = (label: string, r: Rate | null | undefined, color: string, y: number) =>
    r ? (
      <g>
        <text x={0} y={y + 4} fill="#8b998f" fontSize="11" fontFamily="JetBrains Mono">{label}</text>
        <rect x={60} y={y - 9} width={440 * r.pass_rate} height={18} fill={color} opacity=".85" className="grow" />
        <line x1={60 + 440 * r.pass_rate_ci95[0]} x2={60 + 440 * r.pass_rate_ci95[1]} y1={y} y2={y} stroke="#090b0a" strokeWidth="2" />
        <line x1={60 + 440 * r.pass_rate_ci95[0]} x2={60 + 440 * r.pass_rate_ci95[0]} y1={y - 6} y2={y + 6} stroke="#090b0a" strokeWidth="2" />
        <line x1={60 + 440 * r.pass_rate_ci95[1]} x2={60 + 440 * r.pass_rate_ci95[1]} y1={y - 6} y2={y + 6} stroke="#090b0a" strokeWidth="2" />
        <text x={508} y={y + 4} fill="#d8dfd4" fontSize="12" fontFamily="JetBrains Mono" fontWeight="600">{pct(r.pass_rate)}</text>
      </g>
    ) : null
  return (
    <div className="panel rounded p-4">
      <div className="mb-2 flex items-baseline justify-between"><h3 className="font-display text-xl font-bold uppercase tracking-wide">{title}</h3>
        <span className="font-mono text-[11px] text-dim">n = {after?.n ?? before?.n ?? '-'}</span></div>
      <svg viewBox="0 0 560 78" className="w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((t) => <line key={t} x1={60 + 440 * t} x2={60 + 440 * t} y1={0} y2={64} stroke="#1f2924" />)}
        {target != null && <g><line x1={60 + 440 * target} x2={60 + 440 * target} y1={0} y2={64} stroke="#f2b134" strokeDasharray="4 3" /><text x={60 + 440 * target} y={76} fill="#f2b134" fontSize="10" textAnchor="middle" fontFamily="JetBrains Mono">target {pct(target, 0)}</text></g>}
        {row('before', before, '#7f8da0', 20)}
        {row('after', after, '#5be39a', 48)}
      </svg>
      <div className="mt-1 grid grid-cols-2 gap-2 font-mono text-[11px] text-dim">
        <span>before {ci(before)}</span><span>after {ci(after)}</span>
        <span>collisions {pct(before?.collision_rate)} {'->'} {pct(after?.collision_rate)}</span>
        <span>mean time of successes {before?.mean_completion_time_s?.toFixed(2) ?? 'n/a'}s {'->'} {after?.mean_completion_time_s?.toFixed(2) ?? 'n/a'}s</span>
      </div>
    </div>
  )
}

const AX: Record<string, string> = { mass_kg: 'mass (kg)', friction: 'friction', sensor_noise_m: 'sensor noise (m)', gripper_delay_steps: 'gripper delay (steps)' }
/** Failure-rate grid over two scenario axes under the DEFAULT policy, from the stored baseline results. */
export function Heatmap({ h }: { h: Heat }) {
  const nb = h.cells.length, S = 54, ox = 70, oy = 8
  const f = (v: number) => (Math.abs(v) < 1 ? v.toFixed(2) : v.toFixed(0))
  return (
    <div className="panel rounded p-4">
      <h3 className="mb-2 font-display text-lg font-bold uppercase tracking-wide">{AX[h.y] ?? h.y} by {AX[h.x] ?? h.x}</h3>
      <svg viewBox={`0 0 ${ox + nb * S + 10} ${oy + nb * S + 46}`} className="w-full" role="img" aria-label="failure rate heatmap">
        {h.cells.map((row, yi) => row.map((c, xi) => {
          const r = c.n ? c.n_fail / c.n : 0, Y = oy + (nb - 1 - yi) * S
          return (
            <g key={`${xi}-${yi}`}>
              <title>{`${c.n_fail} of ${c.n} baseline scenarios fail`}</title>
              <rect x={ox + xi * S} y={Y} width={S - 2} height={S - 2} fill={c.n ? `rgba(255,106,71,${0.08 + 0.85 * r})` : '#10151300'} stroke="#1f2924" />
              {c.n > 0 && <text x={ox + xi * S + S / 2 - 1} y={Y + S / 2 - 3} textAnchor="middle" fill="#fff" fontSize="12" fontFamily="JetBrains Mono" fontWeight="600">{Math.round(r * 100)}%</text>}
              {c.n > 0 && <text x={ox + xi * S + S / 2 - 1} y={Y + S / 2 + 10} textAnchor="middle" fill="#d8dfd4" opacity=".65" fontSize="9" fontFamily="JetBrains Mono">{c.n_fail}/{c.n}</text>}
            </g>
          )
        }))}
        {h.x_edges.map((e, i) => <text key={i} x={ox + i * S - 1} y={oy + nb * S + 12} textAnchor="middle" fill="#8b998f" fontSize="9" fontFamily="JetBrains Mono">{f(e)}</text>)}
        {h.y_edges.map((e, i) => <text key={i} x={ox - 6} y={oy + (nb - i) * S + 3} textAnchor="end" fill="#8b998f" fontSize="9" fontFamily="JetBrains Mono">{f(e)}</text>)}
        <text x={ox + (nb * S) / 2} y={oy + nb * S + 32} textAnchor="middle" fill="#d8dfd4" fontSize="11" fontFamily="Instrument Sans">{AX[h.x] ?? h.x}</text>
        <text transform={`translate(12 ${oy + (nb * S) / 2}) rotate(-90)`} textAnchor="middle" fill="#d8dfd4" fontSize="11" fontFamily="Instrument Sans">{AX[h.y] ?? h.y}</text>
      </svg>
      <p className="font-mono text-[10.5px] text-dim">cell = share of baseline (default policy) scenarios that fail; hover for counts</p>
    </div>
  )
}

/** One-line human summary of a gate check's numbers, taken from the stored observed/threshold fields. */
export function checkLine(c: Check): string {
  const o: any = c.observed ?? {}, t: any = c.threshold ?? {}
  switch (c.id) {
    case 'G1': return o.sample != null ? `${o.sample} baseline scenarios re-run in fresh processes, ${o.mismatches} differing results` : c.details
    case 'G2': return o.targeted != null ? `${o.targeted - o.not_reproduced} of ${o.targeted} targeted failures failed again on the unpatched policy` : c.details
    case 'G3': return o.targeted != null ? `${o.fixed} of ${o.targeted} targeted failures now pass (${pct(o.fixed / o.targeted)}; needs at least ${pct(t.min_fix_rate, 0)})` : c.details
    case 'G4': return o.previously_passing != null
      ? `${o.regressions} of ${o.previously_passing} previously passing scenarios now fail; budget ${t.budget}; strict zero-budget: ${o.strict_zero_budget_pass ? 'would pass' : 'would FAIL'}` : c.details
    case 'G5': return o.n != null
      ? `patched ${o.patched_passes ?? Math.round(o.patched_pass_rate * o.n)}/${o.n} = ${pct(o.patched_passes != null ? o.patched_passes / o.n : o.patched_pass_rate)} (needs at least ${pct(t.min_pass_rate, 0)}); unpatched ${o.unpatched_passes ?? Math.round(o.unpatched_pass_rate * o.n)}/${o.n}; improvement ${pct(o.improvement)} (needs ${pct(t.min_improvement, 0)}); Wilson lower bound ${pct(o.patched_wilson95_lower)} vs unpatched ${pct(o.unpatched_pass_rate)}`
      : c.details
    case 'G6': return o.runs != null ? `${o.runs} runs relied on, ${o.failed_shards} failed shards, ${o.missing_scenarios} missing scenarios` : c.details
    default: return c.details
  }
}

const DESC: Record<string, string> = {
  G1: 'Determinism: a sample of the baseline re-runs identically', G2: 'Reproduced: targeted failures fail again before the fix', G3: 'Fixed: enough targeted failures now pass',
  G4: 'No regressions: previously passing scenarios still pass (within budget)', G5: 'Held-out: a fresh code-made set meets the target, the improvement and the Wilson bound',
  G6: 'Complete: every shard finished, nothing missing',
}
export function GateChecklist({ checks }: { checks: Check[] }) {
  return (
    <ol className="panel divide-y divide-[#1f2924] rounded">
      {checks.map((c, i) => (
        <li key={c.id} className="rise p-4" style={{ animationDelay: `${i * 70}ms` }}>
          <div className="flex flex-wrap items-center gap-3">
            <span className="w-9 font-display text-2xl font-black text-amber">{c.id}</span>
            <Chip status={c.status} />
            <span className="min-w-0 flex-1 text-sm font-medium">{DESC[c.id] ?? c.name}</span>
          </div>
          <p className="mt-1 pl-12 font-mono text-[12px] leading-relaxed text-dim tick">{checkLine(c)}</p>
          {c.status === 'skipped_after_failure' && checkLine(c) !== c.details && <p className="mt-1 pl-12 text-xs text-dim">{c.details}</p>}
          <details className="pl-12 pt-1 text-xs text-dim"><summary className="inline-block text-[11px] underline decoration-dotted">raw observed and threshold</summary>
            <pre className="mt-1 overflow-x-auto rounded bg-black/40 p-2 font-mono text-[11px] text-text">{JSON.stringify({ observed: c.observed, threshold: c.threshold }, null, 1)}</pre></details>
        </li>
      ))}
    </ol>
  )
}
