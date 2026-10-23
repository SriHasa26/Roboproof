import { usePageTitle } from '../motion'

/** Placeholder until Part E: the live console. */
export default function Live() {
  usePageTitle('Live console')
  return (
    <div>
      <div className="eyebrow mb-3">live console</div>
      <h1 className="font-display text-4xl font-extrabold md:text-5xl">Live rehearsal</h1>
      <p className="mt-4 max-w-xl text-dim">The live console is being built. Live runs are offline in this build.</p>
    </div>
  )
}
