import { Link, useParams } from 'react-router-dom'
import { CandTable, Evidence, Hyp, Replays, Run as RunT, dataUrl, pct, short, usd, useData } from '../lib'
import { Skeleton, usePageTitle } from '../motion'
import FailureMapPanel from '../three/FailureMapPanel'
import VerifyPanel from '../play/Verify'
import ModelCalls, { CallsSrc } from '../play/ModelCalls'
import { BadgeRow, GateChecklist, Heatmap, Note, RatePair, Section, Stamp } from '../ui'

const DEFAULT: Record<string, number> = { grip_force: 15, approach_speed: 0.3, lift_height: 0.15, lift_speed: 0.3, grasp_hold_steps: 10, place_slow_factor: 1, retry_count: 0 }

function evNumbers(e: Evidence): string {
  const d = e.data
  const ciT = d.fail_rate_ci95 ? ` (95% CI ${pct(d.fail_rate_ci95[0], 0)} to ${pct(d.fail_rate_ci95[1], 0)})` : ''
  switch (e.kind) {
    case 'bin': case 'tree_leaf': return `${d.n_fail} of ${d.n} baseline scenarios fail = ${pct(d.fail_rate)}${ciT}`
    case 'interaction': return `${d.n_fail} of ${d.n} fail = ${pct(d.fail_rate)}, ${pct(d.excess_over_max_marginal, 0)} above the larger single-axis rate`
    case 'metrics': return `overall pass rate ${pct(d.pass_rate)}, collisions ${pct(d.collision_rate)}`
    case 'reasons': return Object.entries(d.counts as Record<string, number>).map(([k, v]) => `${k} ${v}`).join(', ')
    default: return ''
  }
}

function Changes({ policy }: { policy: Record<string, number> }) {
  const diffs = Object.entries(policy).filter(([k, v]) => k in DEFAULT && v !== DEFAULT[k])
  return <span className="font-mono text-xs">{diffs.length ? diffs.map(([k, v]) => `${k} ${DEFAULT[k]} -> ${v}`).join(', ') : 'no change from the default policy'}</span>
}

function CandidateTable({ t }: { t: CandTable }) {
  return (
    <div className="panel mb-6 overflow-x-auto rounded">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b hair p-3">
        <h3 className="font-display">Attempt {t.attempt}</h3>
        <span className="font-mono text-[11px] text-dim">regression budget {t.regression_budget ?? 'n/a'} {t.v1_single_patch ? ' | pipeline v1: one patch per attempt, no candidate table' : ''}</span>
      </div>
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="font-mono text-[11px] uppercase tracking-wider text-dim">
          <tr><th className="p-3">#</th><th>Applied changes</th><th>Targeted fixed</th><th>Per hypothesis</th><th>Regressions</th><th>Pass rate</th><th /></tr>
        </thead>
        <tbody>
          {t.candidates.map((c) => {
            const over = t.regression_budget != null && c.regressions != null && c.regressions > t.regression_budget
            return (
              <tr key={c.index} className={`border-t hair ${c.selected ? 'bg-amber/10' : ''}`}>
                <td className="p-3 font-mono text-xs">{c.index}</td>
                <td className="font-mono text-xs">{Object.entries(c.applied).map(([k, v]) => <span key={k} className="mr-1 inline-block rounded-sm border hair px-1.5 py-0.5">{k} {v}</span>)}</td>
                <td className="font-mono text-xs tick">{c.fixed == null ? 'n/a' : `${c.fixed}/${c.targeted} (${pct((c.fixed ?? 0) / (c.targeted || 1), 0)})`}</td>
                <td className="font-mono text-[11px] text-dim">{Object.entries(c.per_hypothesis_fixed).map(([h, v]) => `${h} ${v}`).join('  ') || '-'}</td>
                <td className={`font-mono text-xs ${over ? 'text-verm' : ''}`}>{c.regressions == null ? 'n/a' : `${c.regressions}/${c.previously_passing}`}{over && ' over budget'}</td>
                <td className="font-mono text-xs">{c.pass_rate == null ? '-' : pct(c.pass_rate)}</td>
                <td className="pr-3 text-right">{c.selected && <span className="rounded-sm bg-amber px-1.5 py-0.5 font-mono text-[10px] font-bold text-ink">SELECTED</span>}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {t.dropped.length > 0 && <p className="border-t hair p-3 font-mono text-[11px] text-dim">dropped by validation: {t.dropped.map((d) => `#${d.index} ${d.reason}`).join('; ')}</p>}
      {t.diversity_violations.length > 0 && <p className="border-t hair p-3 font-mono text-[11px] text-amber">diversity requirement not met: {t.diversity_violations.join('; ')}</p>}
    </div>
  )
}

export function HypCard({ h }: { h: Hyp }) {
  return (
    <div className="panel rounded p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-3xl font-bold text-amber">{h.id}</span>
        {Object.entries(h.region).map(([k, v]) => <span key={k} className="rounded-sm border hair px-1.5 py-0.5 font-mono text-[11px]">{k} {v[0]} to {v[1]}</span>)}
        <span className="ml-auto font-mono text-[11px] text-dim">{h.targeted_failures} targeted failures (counted by code)</span>
      </div>
      <p className="mt-2 font-mono text-[11px] uppercase tracking-wider text-dim">levers the model named: {h.levers.map((l) => `${l.param} ${l.direction}`).join(', ')}</p>
      <ul className="mt-3 space-y-1">
        {h.evidence.map((e) => (
          <li key={e.id} className="text-sm"><span className="mr-2 rounded-sm bg-white/10 px-1.5 py-0.5 font-mono text-[11px]">{e.id}</span>
            <span className="text-dim">{e.title}:</span> <span className="font-mono text-xs tick">{evNumbers(e)}</span></li>
        ))}
      </ul>
      <details className="mt-3 text-sm"><summary className="inline-block rounded-sm border border-amber/40 px-2 py-0.5 font-mono text-[11px] text-amber">the model's words (UNVERIFIED opinion)</summary>
        <div className="mt-2 space-y-1 border-l-2 border-amber/40 pl-3 text-dim"><p>{h.model_text_unverified.statement}</p><p><i>Mechanism:</i> {h.model_text_unverified.mechanism}</p><p><i>Prediction:</i> {h.model_text_unverified.prediction}</p></div></details>
    </div>
  )
}

export default function RunPage() {
  const { id = '' } = useParams()
  const { data: r, error } = useData<RunT>(`runs/${id}.json`)
  const rp = useData<Replays>('replays.json')
  usePageTitle(`Run ${id}`)
  if (error) return <p className="font-mono text-sm text-verm">No such run ({error}). <Link className="underline" to="/results">Back to the results</Link></p>
  if (!r) return <Skeleton className="h-96 w-full" />
  return <RunReport r={r} replays={rp.data} back={['/results', 'results']} />
}

/** The run detail view; fed by recorded JSON (static site) or by the live API's report endpoint. */
export function RunReport({ r, replays, back, map, calls }: { r: RunT; replays: Replays | null; back: [string, string]; map?: { file?: string; url?: string } | null; calls?: CallsSrc | null }) {
  const rp = { data: replays }
  const t = r.timing, tot = Math.max(t.wall_clock_s, 1)
  const seg: [string, number, string][] = [['LLM calls', t.llm_s, '#f2b134'], ['candidate evaluation (simulator)', t.candidate_evals_s, '#5be39a'], ['other simulation and code', t.other_simulation_s, '#7f8da0']]
  const g = r.generator
  return (
    <div>
      <Link to={back[0]} className="font-mono text-xs text-dim hover:text-amber">&larr; {back[1]}</Link>
      <header className="rise mb-10 mt-3 flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-[.3em] text-amber">run report</div>
          <h1 className="font-display [overflow-wrap:anywhere]">{r.id}</h1>
          <div className="mt-3"><BadgeRow b={r.badges} /></div>
          <p className="mt-3 font-mono text-xs text-dim">master seed {r.master_seed ?? 'not recorded'} | {r.attempts_used} attempt(s) | G5 {r.g5_executed ? 'executed' : 'not executed'} | {r.analysis_set.n} analysis scenarios ({r.analysis_set.n_coverage} coverage, {r.analysis_set.n_targeted} from model-proposed regions)</p>
        </div>
        <Stamp verdict={r.verdict} />
      </header>

      {r.error && <Note tone="warn">This run ended with an error: {r.error}</Note>}

      <Section kicker="the gate" title="Checklist" delay={40}>
        <GateChecklist checks={r.gate.checks} />
        <p className="mt-3 font-mono text-[12px] text-dim">
          Strict zero-regression result (shown next to the budgeted G4): {r.gate.strict_zero_budget.regressions == null ? 'n/a' : `${r.gate.strict_zero_budget.regressions} regressions, ${r.gate.strict_zero_budget.pass ? 'would pass' : 'would FAIL'}`}.
          {r.gate.regressed_scenario_ids.length > 0 && ` Regressed scenario ids: ${r.gate.regressed_scenario_ids.join(', ')}.`}
        </p>
      </Section>

      <Section kicker="before and after" title="Pass rates" delay={80}>
        <div className="grid gap-4 md:grid-cols-2">
          <RatePair title="Analysis set (seen by the fixer)" before={r.metrics.analysis?.before} after={r.metrics.analysis?.after} />
          {r.metrics.verification ? <RatePair title="Held-out set (never seen)" before={r.metrics.verification.before} after={r.metrics.verification.after} target={0.9} />
            : <div className="panel rounded p-4"><h3 className="font-display">Held-out set</h3><p className="mt-2 text-sm text-dim">Not run: an earlier check failed, so the single-use held-out block was not spent.</p></div>}
        </div>
        {r.final_patch && <p className="mt-3 text-sm text-dim">Final patch tested by the gate: <Changes policy={r.final_patch} /></p>}
      </Section>

      <Section kicker="the fixer" title="Candidates, tested by code" delay={120}>
        <Note>
          The model proposes candidates; code measures every one on the analysis set and chooses. Rule: among candidates within the regression budget take the highest targeted fix;
          ties go to fewer changed parameters, then lower grip force. If none is within budget, take the fewest regressions. Only the selected row goes through the gate.
        </Note>
        <div className="mt-4">{r.candidate_tables.map((c) => <CandidateTable key={c.attempt} t={c} />)}</div>
      </Section>

      <Section kicker="the analyst" title="Hypotheses" delay={160}>
        <Note tone="warn">Numbers below are looked up in the evidence by id. The model's wording is shown only on request and is an unverified opinion.</Note>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">{r.hypotheses.map((h) => <HypCard key={h.id} h={h} />)}</div>
      </Section>

      {r.badges.mode === 'official' && r.badges.recorded && <VerifyPanel runId={r.id} />}

      {map !== null && <FailureMapPanel {...(map ?? { file: `scenarios/${r.id}.json` })} />}

      <Section kicker="where it fails" title="Failure heatmaps" delay={200}>
        <div className="grid gap-4 md:grid-cols-2">{r.heatmaps.map((h) => <Heatmap key={h.x + h.y} h={h} />)}</div>
      </Section>

      <Section kicker="the scenarios" title="Generator" delay={240}>
        <div className="panel rounded p-4">
          <p className="text-sm">Source <b className={g.source === 'llm' ? 'text-phos' : 'text-amber'}>{g.source}</b>{g.source === 'coverage_only_fallback' && ' (every model failed, so the whole set is code-made coverage)'} | model <span className="font-mono text-xs">{short(g.model)}</span></p>
          <p className="mt-1 font-mono text-[11px] text-dim">trail: {g.trail.map((x) => `${x.stage} -> ${x.outcome}`).join('  |  ') || 'none'}</p>
          <ul className="mt-3 space-y-1 text-sm">
            {g.regions_used.map((x) => <li key={x.name}><span className="font-mono text-xs">{x.name}</span> <span className="font-mono text-[11px] text-dim">{Object.entries(x.ranges).map(([k, v]) => `${k} ${v[0]} to ${v[1]}`).join(', ')}</span></li>)}
          </ul>
          {g.dropped_regions.length > 0 && <details className="mt-3"><summary className="inline-block text-xs underline decoration-dotted">{g.dropped_regions.length} region(s) dropped by validation</summary>
            <ul className="mt-1 space-y-1 font-mono text-[11px] text-dim">{g.dropped_regions.map((d) => <li key={d.name}>{d.name}: {d.reason}</li>)}</ul></details>}
          {g.clamped_values.length > 0 && <p className="mt-2 font-mono text-[11px] text-dim">{g.clamped_values.length} value(s) clamped into bounds by code</p>}
        </div>
      </Section>

      <Section kicker="time and money" title="Timing and cost" delay={280}>
        <div className="panel rounded p-4">
          <div className="flex h-5 w-full overflow-hidden rounded-sm">{seg.map(([l, v, c]) => <div key={l} title={`${l}: ${v}s`} style={{ width: `${(v / tot) * 100}%`, background: c }} />)}</div>
          <ul className="mt-2 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-dim">{seg.map(([l, v, c]) => <li key={l}><span className="mr-1.5 inline-block h-2 w-2" style={{ background: c }} />{l} {v.toFixed(0)}s ({pct(v / tot, 0)})</li>)}<li>wall-clock {t.wall_clock_s.toFixed(0)}s</li></ul>
          <p className="mt-3 font-mono text-xs text-dim">{r.tokens.llm_calls} LLM calls, {r.tokens.prompt} prompt and {r.tokens.completion} completion tokens (hidden reasoning is billed as completion). Estimated cost {usd(r.cost.estimated_usd)}: {r.cost.note}.</p>
          <p className="mt-1 font-mono text-[11px] text-dim">commit {String(r.provenance.commit ?? '').slice(0, 10)} | tag {r.provenance.tag ?? 'n/a'} | image {String(r.provenance.image_build_id ?? '').slice(7, 19)} | runner {r.provenance.runner_name ?? 'n/a'}</p>
        </div>
      </Section>

      {calls !== null && <ModelCalls src={calls ?? { file: `calls/${r.id}.json`, origin: 'recorded', label: r.id }} />}

      {rp.data && rp.data.run === r.id && (
        <Section kicker="see it" title="Replay: the same scenario, before and after" delay={320}>
          <Note>Same scenario and seed, frozen simulator. Recorded from the simulator, not generated by a model.</Note>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {(['baseline', 'patched'] as const).map((k) => {
              const x = rp.data![k]
              return (
                <figure key={k} className="panel rounded p-3">
                  <img src={dataUrl(x.gif.replace(/^replays\//, 'replays/'))} alt={`${k} policy replay`} className="w-full rounded-sm" loading="lazy" />
                  <figcaption className="mt-2 font-mono text-[11px] text-dim">
                    <b className={x.result.success ? 'text-phos' : 'text-verm'}>{k === 'baseline' ? 'DEFAULT POLICY' : 'PATCHED POLICY'}: {x.result.success ? 'success' : x.result.failure_reason}</b>
                    {' '}| place error {Number(x.result.final_place_error_m).toFixed(3)} m | time {Number(x.result.completion_time_s).toFixed(2)} s<br />
                    <Changes policy={x.policy} />
                  </figcaption>
                </figure>
              )
            })}
          </div>
          <p className="mt-2 font-mono text-[11px] text-dim">scenario {String(rp.data.scenario.id)} | seed {rp.data.seed} | mass {Number(rp.data.scenario.mass_kg).toFixed(2)} kg, friction {Number(rp.data.scenario.friction).toFixed(2)}, gripper delay {String(rp.data.scenario.gripper_delay_steps)} steps</p>
        </Section>
      )}
    </div>
  )
}
