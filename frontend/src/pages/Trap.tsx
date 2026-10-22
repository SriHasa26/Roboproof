import { Trap, pct, useData } from '../lib'
import { GateChecklist, Note, RatePair, Section, Stamp } from '../ui'

export default function TrapPage() {
  const { data: t, error } = useData<Trap>('trap.json')
  if (error) return <p className="font-mono text-sm text-verm">Could not load: {error}</p>
  if (!t) return <p className="font-mono text-sm text-dim">loading...</p>
  const failing = t.checks.filter((c) => c.status === 'fail').map((c) => c.id)
  return (
    <div>
      <header className="rise mb-10 flex flex-wrap items-end justify-between gap-6">
        <div>
          <div className="mb-2 font-mono text-[11px] uppercase tracking-[.3em] text-verm">the gate must be able to say no</div>
          <h1 className="font-display text-5xl font-black uppercase leading-[.95] md:text-7xl">A tempting fix,<br />rejected.</h1>
          <span className="mt-4 inline-block rounded-sm border-2 border-amber px-3 py-1 font-mono text-sm font-bold uppercase tracking-widest text-amber">{t.label}</span>
        </div>
        <Stamp verdict={t.verdict} />
      </header>

      <Note tone="warn">
        This is a hand-written patch used to show that the gate rejects a plausible but insufficient fix. It was not produced by a model. The result below is the stored gate
        result from the rehearsal run (rehearsal seeds, not held-out ones); nothing is recomputed in this page. {t.note}
      </Note>

      <Section kicker="the patch" title="What it changes" delay={40}>
        <div className="panel rounded p-4">
          <p className="font-mono text-sm">{Object.entries(t.patch).map(([k, v]) => <span key={k} className="mr-2 inline-block rounded-sm border hair px-2 py-0.5">{k} {v}</span>)}</p>
          <p className="mt-2 text-sm text-dim">{t.patch_description}. It is the obvious fix for heavy, slippery cubes: a stronger grip and a longer hold.</p>
          <p className="mt-1 font-mono text-[11px] text-dim">targeting: {t.targeting}</p>
        </div>
      </Section>

      <Section kicker="why it was rejected" title={`Failing checks: ${failing.join(' and ') || 'none'}`} delay={80}>
        <GateChecklist checks={t.checks} />
        <p className="mt-3 font-mono text-[12px] text-dim">
          It fixed most of the targeted failures (G3 passed) but broke {t.regressed_scenario_ids.length} scenarios that passed before, more than the budget allows (G4), and it did not reach the held-out
          target (G5, run as a diagnostic after G4 had already failed). Strict zero-budget: {t.strict_zero_budget.regressions} regressions.
        </p>
      </Section>

      <Section kicker="before and after" title="Pass rates" delay={120}>
        <div className="grid gap-4 md:grid-cols-2">
          <RatePair title="Analysis set" before={t.metrics.analysis?.before} after={t.metrics.analysis?.after} />
          <RatePair title="Held-out style set (rehearsal block)" before={t.metrics.verification?.before} after={t.metrics.verification?.after} target={0.9} />
        </div>
        <p className="mt-3 text-sm text-dim">The patch is not useless: it lifts the pass rate, just not enough, and not safely. That is the case the gate exists for. Held-out after: {pct(t.metrics.verification?.after.pass_rate)}.</p>
      </Section>
    </div>
  )
}
