import { Link } from 'react-router-dom'
import { Row, Study, Summary, ci, pct, short, usd, useData } from '../lib'
import { IntervalPlot, Note, Section, Stamp } from '../ui'

const STEPS: [string, string, string][] = [
  ['01', 'Generate scenarios', 'Nemotron Nano proposes risky regions (Nemotron Super is the fallback). Code adds a coverage sweep so no region is left blank.'],
  ['02', 'Simulate', 'PyBullet, deterministic, in a local container. Same seed, same result.'],
  ['03', 'Analyse', 'Code computes the evidence. Nemotron Ultra explains it as hypotheses; its words are labelled unverified.'],
  ['04', 'Propose fixes', 'Ultra proposes 4 diverse patches. Code tests every one on the analysis set and picks one by a fixed rule.'],
  ['05', 'Gate', 'Pure code, six checks (G1 to G6), including a fresh held-out set the AI never saw.'],
  ['06', 'Verdict', 'VERIFIED, FAILED or UNVERIFIED. If the fix cannot be proven, it says so.'],
]

function Loading({ error }: { error: string | null }) {
  return <p className="font-mono text-sm text-dim">{error ? `Could not load data: ${error}` : 'loading recorded data...'}</p>
}

export default function Overview() {
  const off = useData<Summary>('official.json')
  const studies = useData<Study[]>('studies.json')
  const a = off.data?.aggregate
  return (
    <div>
      <header className="rise mb-14 grid items-end gap-8 md:grid-cols-[1.5fr_1fr]">
        <div>
          <div className="mb-3 font-mono text-[11px] uppercase tracking-[.3em] text-amber">Proof-of-robustness report</div>
          <h1 className="font-display text-6xl font-black uppercase leading-[.9] tracking-tight md:text-8xl">
            An AI that fixes robot policies <span className="text-amber">and must prove it.</span>
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-dim">
            RoboProof stress-tests a simulated pick-and-place gripper, explains why it fails, proposes parameter fixes, and certifies a fix only when a
            deterministic gate proves it on fresh scenarios the AI never saw. The language models never decide pass or fail; the simulator and the gate do.
          </p>
        </div>
        {a && (
          <div className="panel rounded p-6">
            <div className="font-mono text-[11px] uppercase tracking-widest text-dim">official batch, 5 pre-registered runs</div>
            <div className="mt-2 font-display text-7xl font-black leading-none text-phos tick">{a.verified_rate.verified}<span className="text-3xl text-dim"> of {a.verified_rate.of_runs}</span></div>
            <div className="mt-1 font-display text-2xl font-bold uppercase tracking-wide">VERIFIED</div>
            <p className="mt-3 font-mono text-[12px] leading-relaxed text-dim">Wilson 95% interval {pct(a.verified_rate.wilson95[0], 0)} to {pct(a.verified_rate.wilson95[1], 0)}. Five runs is a small sample; every run is shown below.</p>
          </div>
        )}
      </header>

      <Section kicker="the results" title="Official batch">
        <Note>
          Pre-registered before any official run (seeds, thresholds and reporting rules are fixed in the protocol). Each run used its own single-use held-out set of 400 scenarios.
          Nothing was re-rolled or discarded. <b className="text-text">Run 1 is the headline run by rule.</b>
        </Note>
        {off.data ? (
          <div className="panel mt-4 overflow-x-auto rounded">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="border-b hair font-mono text-[11px] uppercase tracking-wider text-dim">
                <tr><th className="p-3">Run</th><th>Seed</th><th>Verdict</th><th>Attempts</th><th>Held-out pass rate: before to after (Wilson 95%)</th><th>Est. cost</th><th /></tr>
              </thead>
              <tbody>
                {off.data.runs.map((r: Row, i) => (
                  <tr key={r.run_id} className="rise border-b hair last:border-0 hover:bg-white/[.03]" style={{ animationDelay: `${i * 80}ms` }}>
                    <td className="p-3 font-mono text-xs">{i + 1}{i === 0 && <span className="ml-2 rounded-sm bg-amber px-1.5 py-0.5 text-[10px] font-bold text-ink">HEADLINE</span>}</td>
                    <td className="font-mono text-xs">{r.master_seed}</td>
                    <td><Stamp verdict={r.verdict} size="sm" /></td>
                    <td className="font-mono text-xs">{r.attempts}</td>
                    <td className="font-mono text-xs tick">{ci(r.verification_before)} <span className="text-amber">to</span> {ci(r.verification_after)}</td>
                    <td className="font-mono text-xs">{usd(r.estimated_cost_usd)}</td>
                    <td className="pr-3 text-right"><Link className="font-mono text-xs text-amber underline decoration-dotted underline-offset-4 hover:text-text" to={`/run/${r.run_id}`}>open report</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Loading error={off.error} />}
      </Section>

      <Section kicker="how reliable is the pipeline" title="Three studies, side by side" delay={80}>
        <Note>
          Fraction of full runs that ended VERIFIED, with the Wilson 95% interval. The two rehearsal studies used rehearsal seeds, not held-out ones. Intervals overlap heavily: do not read
          these as a proven improvement from v1 to v2.
        </Note>
        {studies.data && off.data ? (
          <div className="panel mt-4 rounded p-4 md:p-6">
            <IntervalPlot items={[
              ...studies.data.map((s) => ({ label: `Pipeline ${s.pipeline_version} rehearsal`, sub: s.aggregate.verdict_counts['ERROR (no verdict)'] ? `${s.aggregate.verdict_counts['ERROR (no verdict)']} run(s) ended with no verdict` : 'all runs reached a verdict',
                k: s.aggregate.verified_rate.verified, n: s.aggregate.verified_rate.of_runs, lo: s.aggregate.verified_rate.wilson95[0], hi: s.aggregate.verified_rate.wilson95[1] })),
              { label: 'Pipeline v2 OFFICIAL', sub: 'held-out seeds, pre-registered', k: off.data.aggregate.verified_rate.verified, n: off.data.aggregate.verified_rate.of_runs,
                lo: off.data.aggregate.verified_rate.wilson95[0], hi: off.data.aggregate.verified_rate.wilson95[1] },
            ]} />
          </div>
        ) : <Loading error={studies.error ?? off.error} />}
      </Section>

      <Section kicker="the pipeline" title="Six stages" delay={120}>
        <ol className="grid gap-px overflow-hidden rounded border hair bg-line md:grid-cols-3">
          {STEPS.map(([n, t, d]) => (
            <li key={n} className="bg-panel p-5">
              <div className="font-display text-5xl font-black text-amber/80">{n}</div>
              <h3 className="mt-1 font-display text-xl font-bold uppercase tracking-wide">{t}</h3>
              <p className="mt-1 text-sm leading-relaxed text-dim">{d}</p>
            </li>
          ))}
        </ol>
        {off.data?.runs[0] && (
          <p className="mt-4 font-mono text-[12px] text-dim">
            Models used: generator {short(off.data.runs[0].generator?.model)}; analyst and fixer Nemotron-3-Ultra-550b. Total estimated cost of the five official runs: {usd(a?.total_estimated_cost_usd)} (estimate; billing UNCONFIRMED).
          </p>
        )}
      </Section>

      <Section kicker="read before you trust" title="Honesty" delay={160}>
        <div className="grid gap-4 md:grid-cols-3">
          {[
            ['Simulation only', 'A simplified gripper in PyBullet. Nothing was run on a real robot.'],
            ['Local runner, not Nebius', 'Simulations ran in a local container, not on Nebius Serverless Jobs. Language-model calls used Nebius Token Factory with NVIDIA Nemotron models.'],
            ['Small sample, honest failures', 'Failed runs and near misses are shown, not hidden. The 0.90 target was never lowered.'],
          ].map(([t, d]) => (
            <div key={t} className="panel rounded p-5"><h3 className="font-display text-xl font-bold uppercase tracking-wide text-amber">{t}</h3><p className="mt-1 text-sm leading-relaxed text-dim">{d}</p></div>
          ))}
        </div>
        <p className="mt-4 text-sm"><Link className="text-amber underline decoration-dotted underline-offset-4" to="/about">Read the full list of limits</Link></p>
      </Section>
    </div>
  )
}
