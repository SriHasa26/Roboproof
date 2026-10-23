import { Link } from 'react-router-dom'
import { Row, Study, Summary, ci, pct, short, usd, useData } from '../lib'
import { CountUp, Reveal, Skeleton, usePageTitle } from '../motion'
import { IntervalPlot, Note, Section, Stamp } from '../ui'
import FailureMapPanel from '../three/FailureMapPanel'

export default function Results() {
  usePageTitle('Results')
  const off = useData<Summary>('official.json')
  const studies = useData<Study[]>('studies.json')
  const a = off.data?.aggregate
  return (
    <div>
      <header className="mb-12 grid items-end gap-8 md:grid-cols-[1.5fr_1fr]">
        <Reveal>
          <div className="eyebrow mb-3">results</div>
          <h1 className="font-display">The official batch, <span className="text-grad">with every run shown.</span></h1>
          <p className="mt-5 max-w-2xl text-lg leading-relaxed text-dim">
            Five pre-registered runs of the frozen pipeline, each on its own single-use held-out set of 400 scenarios. Language models never decide pass or fail; the simulator and the gate do.
          </p>
        </Reveal>
        {a ? (
          <Reveal delay={0.1}>
            <div className="glass p-6 shadow-glowP">
              <div className="eyebrow !text-phos">official batch, small sample</div>
              <div className="mt-2 font-display text-7xl font-bold leading-none text-phos"><CountUp value={a.verified_rate.verified} /><span className="text-3xl text-dim"> of {a.verified_rate.of_runs}</span></div>
              <div className="mt-1 font-display text-xl font-bold">VERIFIED</div>
              <p className="mt-3 font-mono text-[12px] leading-relaxed text-dim">Wilson 95% interval {pct(a.verified_rate.wilson95[0])} to {pct(a.verified_rate.wilson95[1])}. Five runs is a small sample.</p>
            </div>
          </Reveal>
        ) : <Skeleton className="h-44" />}
      </header>

      <Section kicker="the official batch" title="Five runs, nothing re-rolled">
        <Note>
          Pre-registered before any official run: seeds, thresholds and reporting rules are fixed in the protocol. Nothing was re-rolled or discarded. <b className="text-text">Run 1 is the headline run by rule.</b>
        </Note>
        {off.data ? (
          <div className="glass mt-4 overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b hair font-mono text-[11px] uppercase tracking-wider text-dim">
                <tr><th className="p-3">Run</th><th>Seed</th><th>Verdict</th><th>Attempts</th><th>Held-out pass rate: before to after (Wilson 95%)</th><th>Est. cost</th><th /></tr>
              </thead>
              <tbody>
                {off.data.runs.map((r: Row, i) => (
                  <tr key={r.run_id} className="border-b hair transition-colors last:border-0 hover:bg-white/[.04]">
                    <td className="p-3 font-mono text-xs">{i + 1}{i === 0 && <span className="ml-2 rounded-full bg-amber px-2 py-0.5 text-[10px] font-bold text-ink">HEADLINE</span>}</td>
                    <td className="font-mono text-xs">{r.master_seed ?? 'n/a'}</td>
                    <td><Stamp verdict={r.verdict} size="sm" /></td>
                    <td className="font-mono text-xs">{r.attempts}</td>
                    <td className="py-3 font-mono text-xs tick">{ci(r.verification_before)} <span className="text-amber">to</span> {ci(r.verification_after)}</td>
                    <td className="font-mono text-xs">{usd(r.estimated_cost_usd)}</td>
                    <td className="pr-3 text-right"><Link className="font-mono text-xs text-amber underline decoration-dotted underline-offset-4 hover:text-text" to={`/runs/${r.run_id}`}>open report</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Skeleton className="mt-4 h-64" />}
      </Section>

      <Section kicker="how reliable is the pipeline" title="Three studies, side by side" delay={60}>
        <Note>
          Fraction of full runs that ended VERIFIED, with the Wilson 95% interval. The two rehearsal studies used rehearsal seeds, not held-out ones. Intervals overlap heavily: do not read
          these as a proven improvement from v1 to v2.
        </Note>
        {studies.data && off.data ? (
          <div className="glass mt-4 p-4 md:p-6">
            <IntervalPlot items={[
              ...studies.data.map((s) => ({ label: `Pipeline ${s.pipeline_version} rehearsal`, sub: s.aggregate.verdict_counts['ERROR (no verdict)'] ? `${s.aggregate.verdict_counts['ERROR (no verdict)']} run(s) ended with no verdict` : 'all runs reached a verdict',
                k: s.aggregate.verified_rate.verified, n: s.aggregate.verified_rate.of_runs, lo: s.aggregate.verified_rate.wilson95[0], hi: s.aggregate.verified_rate.wilson95[1] })),
              { label: 'Pipeline v2 OFFICIAL', sub: 'held-out seeds, pre-registered', k: off.data.aggregate.verified_rate.verified, n: off.data.aggregate.verified_rate.of_runs,
                lo: off.data.aggregate.verified_rate.wilson95[0], hi: off.data.aggregate.verified_rate.wilson95[1] },
            ]} />
          </div>
        ) : <Skeleton className="mt-4 h-56" />}
      </Section>

      <Reveal>
        <p className="mb-3 text-sm text-dim">The map below shows the headline run (run 1): every scenario of its analysis set under the unpatched default policy. The same map is on each run page.</p>
        <FailureMapPanel file="scenarios/official_01_seed3101.json" />
      </Reveal>

      {off.data?.runs[0] && (
        <p className="font-mono text-[12px] text-dim">
          Models used: generator {short(off.data.runs[0].generator?.model)}; analyst and fixer Nemotron-3-Ultra-550b. Total estimated cost of the five official runs: {usd(a?.total_estimated_cost_usd)} (estimate; billing UNCONFIRMED).
        </p>
      )}
    </div>
  )
}
