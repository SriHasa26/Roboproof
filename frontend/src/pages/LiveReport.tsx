import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Run, load } from '../lib'
import { Skeleton, usePageTitle } from '../motion'
import { API_BASE, fetchReport } from '../live/api'
import { RunReport } from './Run'

/** Full run detail for a live run (from the API) or for the recorded replay (from the stored report). */
export default function LiveReport() {
  const { id = '' } = useParams()
  usePageTitle('Live run report')
  const [run, setRun] = useState<Run | null>(null)
  const rk = id.startsWith('replay') ? (id.startsWith('replay-') ? id.slice(7) : 'failed') : null
  const [state, setState] = useState<'loading' | 'missing'>('loading')
  useEffect(() => {
    let live = true
    const p = rk ? load<Run>(`live_replay/${rk}/report.json`).catch(() => null) : fetchReport(id)
    p.then((r) => { if (!live) return; if (r) setRun(rk ? { ...r, badges: { ...r.badges, recorded: true } } : r); else setState('missing') })
    return () => { live = false }
  }, [id, rk])
  if (run) {
    const replay = !!rk
    return (
      <div>
        <div role="note" className={`mb-6 rounded-xl border p-3 text-sm ${replay ? 'border-amber bg-amber/10 text-amber' : 'border-verm/40 bg-verm/[.07]'}`}>
          {replay ? 'Recorded replay: this report was built from a real live rehearsal run that was recorded earlier.' : 'Live rehearsal report. A rehearsal is never an official result.'}
        </div>
        {rk === 'verified' && <p className="mb-4 text-xs text-dim">This older recording was made before model-call metadata capture existed, so it has no model-call log (no response ids). It is not reconstructed.</p>}
        <RunReport r={run} replays={null} back={['/live', 'live console']} origin={replay ? 'replay' : 'live'} map={replay ? { file: `live_replay/${rk}/scenarios.json` } : { url: `${API_BASE}/api/runs/${id}/scenarios` }}
          calls={replay ? (rk === 'verified' ? null : { file: `live_replay/${rk}/calls.json`, origin: 'replay', label: 'recorded live run' }) : { url: `${API_BASE}/api/runs/${id}/model_calls`, repliesUrl: `${API_BASE}/api/runs/${id}/replies`, origin: 'live', label: id }} />
      </div>
    )
  }
  if (state === 'missing') return <p className="font-mono text-sm text-verm">No report is available for this run. <Link className="underline" to="/live">Back to the live console</Link></p>
  return <Skeleton className="h-96 w-full" />
}
