import { ReactNode, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useInView } from 'framer-motion'
import { Row, Study, Summary, pct, useData } from '../lib'
import { CountUp, Reveal, Skeleton, useMotionPrefs, usePageTitle } from '../motion'
import { IntervalPlot, Stamp } from '../ui'
import HeroVisual from '../three/HeroVisual'

function Head({ kicker, title, sub }: { kicker: string; title: ReactNode; sub?: string }) {
  return (
    <Reveal className="mb-10 max-w-3xl">
      <div className="eyebrow mb-3">{kicker}</div>
      <h2 className="font-display text-4xl font-extrabold leading-[1.05] md:text-5xl">{title}</h2>
      {sub && <p className="mt-4 text-lg leading-relaxed text-dim">{sub}</p>}
    </Reveal>
  )
}

function Hero() {
  return (
    <section className="relative grid items-center gap-6 pb-16 pt-10 md:grid-cols-[1.05fr_1fr] md:pt-16">
      <div>
        <Reveal><div className="eyebrow mb-5">Proof-of-robustness for robot policies</div></Reveal>
        <Reveal delay={0.05}>
          <h1 className="font-display text-5xl font-extrabold leading-[1.02] sm:text-6xl lg:text-7xl">Robot fixes <span className="text-grad">you can trust.</span></h1>
        </Reveal>
        <Reveal delay={0.12}>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-dim">
            RoboProof stress-tests a robot policy, proposes a fix with NVIDIA Nemotron, and refuses to say &ldquo;verified&rdquo; until a deterministic gate proves it.
          </p>
        </Reveal>
        <Reveal delay={0.2} className="mt-8 flex flex-wrap gap-3">
          <Link to="/live" className="btn btn-primary">Run a live rehearsal <span aria-hidden>&rarr;</span></Link>
          <Link to="/results" className="btn btn-ghost">See the official results</Link>
        </Reveal>
        <Reveal delay={0.28} className="mt-8 flex flex-wrap gap-2">
          <span className="chip">Physical AI, no hardware</span>
          <span className="chip">Nemotron on Nebius Token Factory</span>
          <span className="chip">PyBullet simulation</span>
        </Reveal>
      </div>
      <div className="relative h-[340px] sm:h-[420px] md:h-[500px]">
        <div className="absolute inset-0 -z-10 rounded-full bg-[radial-gradient(closest-side,rgba(242,177,52,.14),transparent)] blur-2xl" aria-hidden />
        <HeroVisual />
      </div>
    </section>
  )
}

const PROBLEMS: [string, string, ReactNode][] = [
  ['Failures hide in combinations', 'A heavy cube is fine. A slippery cube is fine. A heavy, slippery cube with a late gripper breaks. You cannot list these by hand.',
    <svg key="a" viewBox="0 0 120 60" className="h-14 w-28"><g fill="#1f2924">{[0, 1, 2, 3, 4].flatMap((i) => [0, 1, 2].map((j) => <rect key={`${i}${j}`} x={4 + i * 22} y={4 + j * 18} width="18" height="14" rx="3" fill={i >= 3 && j === 0 ? '#ff6a47' : '#1f2924'} />))}</g></svg>],
  ['Diagnosis is manual', 'Someone reads logs, guesses a cause, tweaks a number and re-runs. It is slow, and the guess is hard to test.',
    <svg key="b" viewBox="0 0 120 60" className="h-14 w-28"><path d="M6 46 L30 34 L52 40 L76 16 L112 26" fill="none" stroke="#7f8da0" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /><circle cx="76" cy="16" r="5" fill="#f2b134" /></svg>],
  ['AI fixes can overfit', 'A fix that repairs the failures you showed it can quietly break everything else. Without fresh scenarios you will not notice.',
    <svg key="c" viewBox="0 0 120 60" className="h-14 w-28"><path d="M8 48 C30 10 50 10 60 30 S96 52 112 12" fill="none" stroke="#ff6a47" strokeWidth="3" strokeLinecap="round" /><circle cx="60" cy="30" r="5" fill="#5be39a" /></svg>],
]

function Problem() {
  return (
    <section className="py-16">
      <Head kicker="the problem" title="Fixing a robot is easy. Knowing the fix works is not." />
      <div className="grid gap-4 md:grid-cols-3">
        {PROBLEMS.map(([t, d, icon], i) => (
          <Reveal key={t} delay={i * 0.1}>
            <div className="glass glass-hover h-full p-6">
              <div className="mb-4">{icon}</div>
              <h3 className="font-display text-xl font-bold">{t}</h3>
              <p className="mt-2 leading-relaxed text-dim">{d}</p>
            </div>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

const STEPS: { n: string; name: string; who: string; text: string }[] = [
  { n: '01', name: 'Generate', who: 'Nemotron Nano (Super as fallback) + code', text: 'The model proposes risky regions of the parameter space: mass, friction, size, sensor noise, gripper delay. Code validates every region and adds a Latin-hypercube sweep, so the map has no blank spots.' },
  { n: '02', name: 'Simulate', who: 'PyBullet, deterministic', text: 'Hundreds of seeded scenarios run against the unpatched policy. The same seed always gives the same result, so failures are real, not flaky.' },
  { n: '03', name: 'Analyze', who: 'Code computes the evidence; Nemotron Ultra explains it', text: 'Failure rates per bin and a shallow decision tree come from code. The model turns them into testable hypotheses; its wording is labelled as an unverified opinion.' },
  { n: '04', name: 'Fix', who: 'Nemotron Ultra proposes, code evaluates', text: 'Ultra proposes four bounded patches to numeric control parameters. Code measures every candidate on the analysis set and picks one by a fixed rule.' },
  { n: '05', name: 'Prove', who: 'The deterministic gate (no model)', text: 'Six checks, including a fresh held-out set the AI never saw. Only if all of them pass does the verdict read VERIFIED.' },
]

function StepCard({ s, i, onActive }: { s: (typeof STEPS)[number]; i: number; onActive: (i: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const inView = useInView(ref, { margin: '-45% 0px -45% 0px' })
  useEffect(() => { if (inView) onActive(i) }, [inView, i, onActive])
  return (
    <div ref={ref} className="min-h-[200px] md:min-h-[260px]">
      <div className="glass p-6 md:p-8">
        <div className="flex items-center gap-3"><span className="font-mono text-sm text-amber">{s.n}</span><h3 className="font-display text-3xl font-extrabold">{s.name}</h3></div>
        <div className="mt-1 font-mono text-xs text-phos">{s.who}</div>
        <p className="mt-4 text-lg leading-relaxed text-dim">{s.text}</p>
      </div>
    </div>
  )
}

function HowItWorks() {
  const [active, setActive] = useState(0)
  return (
    <section className="py-16">
      <Head kicker="how it works" title="Five steps from failure to proof." />
      <div className="grid gap-8 md:grid-cols-[260px_1fr]">
        <ol className="relative hidden md:block">
          <div className="sticky top-28 space-y-1 border-l border-white/10 pl-5">
            {STEPS.map((s, i) => (
              <li key={s.n} className={`relative py-2 transition-all ${i === active ? 'translate-x-1' : 'opacity-50'}`}>
                <span className={`absolute -left-[26px] top-1/2 h-3 w-3 -translate-y-1/2 rounded-full border-2 transition-colors ${i <= active ? 'border-amber bg-amber shadow-glowA' : 'border-white/20 bg-ink'}`} />
                <div className="font-mono text-[11px] text-dim">{s.n}</div>
                <div className={`font-display text-xl font-bold ${i === active ? 'text-text' : 'text-dim'}`}>{s.name}</div>
              </li>
            ))}
          </div>
        </ol>
        <div className="space-y-6 md:space-y-10">
          {STEPS.map((s, i) => <StepCard key={s.n} s={s} i={i} onActive={setActive} />)}
        </div>
      </div>
    </section>
  )
}

const GATES: [string, string, string][] = [
  ['G1', 'Determinism', 'Re-run a sample of the baseline: identical outcomes for identical seeds, so failures are real.'],
  ['G2', 'Reproduced', 'Every failure the analyst targeted fails again on the unpatched policy.'],
  ['G3', 'Fixed', 'At least 70% of those targeted failures now pass with the patch.'],
  ['G4', 'No regressions', 'Scenarios that passed before still pass, within a 2% budget. The strict zero-regression count is always shown too.'],
  ['G5', 'Held-out', 'On 400 fresh scenarios the AI never saw: pass rate at least 90%, improvement at least 10 points, and a Wilson 95% lower bound above the unpatched rate.'],
  ['G6', 'Complete', 'Every shard finished. A missing result is never counted as a pass.'],
]

function Gate({ failed }: { failed: Row | undefined }) {
  const after = failed?.verification_after, n = after?.n
  const got = after && n ? Math.round(after.pass_rate * n) : null
  const need = n ? Math.ceil(0.9 * n) : null
  return (
    <section className="py-16">
      <Head kicker="the proof-of-robustness gate" title="Pure code decides. No model gets a vote." sub="The verdict is exactly one of VERIFIED, FAILED or UNVERIFIED. VERIFIED needs all six checks." />
      <div className="grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <ol className="glass divide-y divide-white/[.06]">
          {GATES.map(([id, name, text], i) => (
            <Reveal as="li" key={id} delay={i * 0.07} className="flex gap-4 p-4 md:p-5">
              <motion.span initial={{ scale: 0.6, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }} viewport={{ once: true }} transition={{ delay: 0.25 + i * 0.12, type: 'spring', stiffness: 260, damping: 16 }}
                className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-phos/50 bg-phos/10 font-mono text-xs font-bold text-phos shadow-glowP">{id}</motion.span>
              <div><div className="font-display text-lg font-bold">{name}</div><p className="text-dim">{text}</p></div>
            </Reveal>
          ))}
        </ol>
        <Reveal delay={0.1}>
          <div className="glass relative h-full overflow-hidden p-6 shadow-glowV">
            <div className="eyebrow mb-3 !text-verm">why a FAILED verdict is a feature</div>
            {failed && after && got != null && need != null ? (
              <>
                <div className="mb-4 flex items-center gap-4"><Stamp verdict="FAILED" size="sm" /><span className="font-mono text-xs text-dim">{failed.run_id}</span></div>
                <p className="leading-relaxed">In the official batch, one run did not clear the held-out check: <b className="font-semibold text-text tick">{got} of {n}</b> fresh scenarios passed ({pct(after.pass_rate)}) and the gate needed {need} ({pct(0.9, 0)}).</p>
                <p className="mt-3 leading-relaxed text-dim">The patch looked good on the scenarios the AI had seen. The gate caught that it was not good enough on new ones. The target was not lowered and the run was not repeated. It is reported as FAILED, and counted.</p>
                <Link to={`/runs/${failed.run_id}`} className="mt-5 inline-block font-mono text-sm text-amber underline decoration-dotted underline-offset-4">open this run</Link>
              </>
            ) : <Skeleton className="h-48 w-full" />}
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function Results({ off, studies }: { off: Summary | null; studies: Study[] | null }) {
  const a = off?.aggregate
  return (
    <section className="py-16">
      <Head kicker="results" title="The official batch, as it came out." sub="Five pre-registered runs on single-use held-out seeds. Nothing was re-rolled or discarded." />
      {off && a ? (
        <>
          <div className="grid gap-6 lg:grid-cols-[1fr_1.4fr]">
            <Reveal>
              <div className="glass h-full p-7 shadow-glowP">
                <div className="eyebrow mb-3 !text-phos">VERIFIED rate, small sample</div>
                <div className="font-display text-8xl font-extrabold leading-none text-phos">
                  <CountUp value={a.verified_rate.verified} /><span className="text-4xl text-dim"> of <CountUp value={a.verified_rate.of_runs} /></span>
                </div>
                <p className="mt-4 font-mono text-sm text-dim tick">Wilson 95% interval {pct(a.verified_rate.wilson95[0])} to {pct(a.verified_rate.wilson95[1])}</p>
                <p className="mt-3 text-sm leading-relaxed text-dim">Five runs is a small sample. The v2 rehearsal study on rehearsal seeds was 4 of 8. The intervals overlap heavily: this is not a proven reliability figure.</p>
              </div>
            </Reveal>
            <Reveal delay={0.1}>
              <div className="glass h-full p-5 md:p-6">
                {studies && (
                  <IntervalPlot items={[
                    ...studies.map((s) => ({ label: `Pipeline ${s.pipeline_version} rehearsal`, sub: s.aggregate.verdict_counts['ERROR (no verdict)'] ? `${s.aggregate.verdict_counts['ERROR (no verdict)']} run(s) ended with no verdict` : 'all runs reached a verdict',
                      k: s.aggregate.verified_rate.verified, n: s.aggregate.verified_rate.of_runs, lo: s.aggregate.verified_rate.wilson95[0], hi: s.aggregate.verified_rate.wilson95[1] })),
                    { label: 'Pipeline v2 OFFICIAL', sub: 'held-out seeds, pre-registered', k: a.verified_rate.verified, n: a.verified_rate.of_runs, lo: a.verified_rate.wilson95[0], hi: a.verified_rate.wilson95[1] },
                  ]} />
                )}
              </div>
            </Reveal>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            {off.runs.map((r, i) => (
              <Reveal key={r.run_id} delay={i * 0.07}>
                <Link to={`/runs/${r.run_id}`} className="glass glass-hover block h-full p-4">
                  <div className="flex items-center justify-between font-mono text-[11px] text-dim"><span>Run {i + 1}{i === 0 ? ' (headline)' : ''}</span><span>seed {r.master_seed ?? 'n/a'}</span></div>
                  <div className="my-3"><Stamp verdict={r.verdict} size="sm" /></div>
                  <div className="text-xs text-dim">held-out pass rate</div>
                  <div className="font-display text-3xl font-extrabold tick">
                    {r.verification_after ? <CountUp value={r.verification_after.pass_rate * 100} format={(v) => `${v.toFixed(1)}%`} /> : 'n/a'}
                  </div>
                  <div className="font-mono text-[11px] text-dim">from {pct(r.verification_before?.pass_rate)} unpatched | {r.attempts} attempt{r.attempts === 1 ? '' : 's'}</div>
                </Link>
              </Reveal>
            ))}
          </div>
          <Reveal className="mt-6"><div className="rounded-xl border border-amber/30 bg-amber/[.06] p-4 text-sm leading-relaxed text-amber/90">
            Honest reading: simulation only, a simplified robot, thresholds set on development data. Two of the four VERIFIED runs had a few regressions inside the 2% budget; a strict zero-regression rule would not have passed them.
          </div></Reveal>
          <div className="mt-6"><Link to="/results" className="btn btn-ghost">Full results and failure maps</Link></div>
        </>
      ) : <div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div>}
    </section>
  )
}

function TryIt() {
  return (
    <section className="py-16">
      <Reveal>
        <div className="glass relative overflow-hidden p-8 text-center md:p-14">
          <div className="absolute inset-0 -z-10 bg-[radial-gradient(600px_240px_at_50%_0%,rgba(242,177,52,.16),transparent)]" aria-hidden />
          <div className="eyebrow mb-3">try it</div>
          <h2 className="font-display text-4xl font-extrabold md:text-5xl">Watch the real pipeline run.</h2>
          <p className="mx-auto mt-4 max-w-xl text-lg text-dim">A live rehearsal runs the actual pipeline end to end on rehearsal seeds: real model calls, real simulation, a real gate verdict. It is never an official result.</p>
          <Link to="/live" className="btn btn-primary mt-8">Open the live console <span aria-hidden>&rarr;</span></Link>
        </div>
      </Reveal>
    </section>
  )
}

function Limits() {
  const items = ['A simplified two-finger gripper in simulation. Nothing was run on a real robot.', 'Simulations ran in a local container, not on Nebius Serverless Jobs.', 'Five official runs is a small sample, and the gate thresholds were set on development data.']
  return (
    <section className="py-16">
      <Head kicker="honest limits" title="What RoboProof does not show." />
      <div className="grid gap-4 md:grid-cols-3">
        {items.map((t, i) => <Reveal key={t} delay={i * 0.08}><div className="glass h-full p-5 leading-relaxed text-dim">{t}</div></Reveal>)}
      </div>
      <Reveal className="mt-6"><Link to="/about" className="font-mono text-sm text-amber underline decoration-dotted underline-offset-4">Read the full list of limits</Link></Reveal>
    </section>
  )
}

export default function Landing() {
  usePageTitle('')
  const off = useData<Summary>('official.json')
  const studies = useData<Study[]>('studies.json')
  useMotionPrefs()
  const failed = off.data?.runs.find((r) => r.verdict === 'FAILED')
  return (
    <div>
      <Hero />
      <Problem />
      <HowItWorks />
      <Gate failed={failed} />
      <Results off={off.data} studies={studies.data} />
      <TryIt />
      <Limits />
    </div>
  )
}
