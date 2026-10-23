import { Suspense, lazy, useEffect, useState } from 'react'
import { load } from '../lib'
import { Skeleton, useMotionPrefs } from '../motion'
import type { ScenData } from './FailureMap3D'

const Map3D = lazy(() => import('./FailureMap3D'))

function webgl(): boolean {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')) } catch { return false }
}

/** Interactive 3D failure map of the run's real scenarios. Hidden (renders nothing) when the run has no per-scenario results. */
export default function FailureMapPanel({ file, url }: { file?: string; url?: string }) {
  const { reduce } = useMotionPrefs()
  const [d, setD] = useState<ScenData | null | undefined>(undefined)
  useEffect(() => {
    setD(undefined)
    const p = url ? fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))) : load<ScenData>(file ?? '')
    p.then(setD).catch(() => setD(null))
  }, [file, url])
  if (d === null) return null // no per-scenario results for this run: hide the map rather than fake one
  return (
    <section className="mb-12">
      <div className="eyebrow mb-1">where it fails, in 3D</div>
      <h2 className="mb-4 font-display text-3xl font-extrabold">Failure map</h2>
      {d === undefined ? <Skeleton className="h-[420px]" />
        : reduce || !webgl() ? <p className="glass p-4 text-sm text-dim">The 3D map is off ({reduce ? 'reduced motion and 3D is on' : 'WebGL is not available'}). The 2D heatmaps below show the same baseline results.</p>
          : <div className="glass p-4"><Suspense fallback={<Skeleton className="h-[420px]" />}><Map3D d={d} reduce={reduce} /></Suspense></div>}
    </section>
  )
}
