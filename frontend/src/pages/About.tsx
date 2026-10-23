import { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useData } from '../lib'

function inline(s: string): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
    p.startsWith('**') ? <b key={i} className="font-semibold text-text">{p.slice(2, -2)}</b>
      : p.startsWith('`') ? <code key={i} className="rounded-sm bg-white/10 px-1 font-mono text-[0.85em]">{p.slice(1, -1)}</code> : p)
}

/** Tiny markdown renderer: headings, bullet lists, paragraphs, **bold**, `code`. Enough for docs/LIMITATIONS.md. */
function Markdown({ text }: { text: string }) {
  const out: ReactNode[] = []
  let list: string[] = []
  const flush = (k: number) => {
    if (list.length) { out.push(<ul key={`l${k}`} className="mb-5 space-y-2.5">{list.map((li, i) => <li key={i} className="flex gap-3 leading-relaxed text-dim"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-amber" /><span>{inline(li)}</span></li>)}</ul>); list = [] }
  }
  text.split('\n').forEach((line, k) => {
    if (line.startsWith('- ')) { list.push(line.slice(2)); return }
    flush(k)
    if (line.startsWith('# ')) out.push(<h1 key={k} className="mb-3 font-display text-5xl font-bold leading-none md:text-6xl">{line.slice(2)}</h1>)
    else if (line.startsWith('## ')) out.push(<h2 key={k} className="mb-3 mt-10 font-display text-3xl font-bold text-amber">{line.slice(3)}</h2>)
    else if (line.trim()) out.push(<p key={k} className="mb-4 leading-relaxed text-dim">{inline(line)}</p>)
  })
  flush(9999)
  return <>{out}</>
}

export default function About() {
  const { data, error } = useData<string>('LIMITATIONS.md')
  return (
    <div className="rise max-w-3xl">
      {error ? <p className="font-mono text-sm text-verm">Could not load the limitations text: {error}</p> : data ? <Markdown text={data} /> : <p className="font-mono text-sm text-dim">loading...</p>}
      <div className="glass mt-10 p-5">
        <div className="eyebrow mb-2">don't trust it, check it</div>
        <h2 className="text-2xl">How to verify in 2 minutes</h2>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-dim">
          <li>Open an official run (<Link className="text-amber underline decoration-dotted underline-offset-4" to="/runs/official_03_seed3303">official_03</Link>, the one that FAILED) and press <b className="text-text">Verify this result</b>. The backend recomputes the gate numbers and re-simulates that run's analysis set now; every row shows stored versus recomputed.</li>
          <li>Press <b className="text-text">Re-run in Playground</b> on a run page to watch a recorded scenario reproduce with its stored seed, then change a slider and see the result change.</li>
          <li>Open the <b className="text-text">Model calls</b> panel: real Nebius calls with latency, tokens and the raw replies; live runs also show the provider's response ids.</li>
          <li>Look for the chip on each panel: <b className="text-text">LIVE</b> (computed now), <b className="text-text">RECORDED</b> (stored artifact) or <b className="text-text">REPLAY</b>. The navbar badge says whether a backend is online.</li>
          <li>In a terminal: <span className="font-mono text-xs text-text">scripts/dock.sh python scripts/verify_official.py</span> re-checks all five runs, the seed ledger, the protocol date and the frozen-pipeline hash; <span className="font-mono text-xs text-text">scripts/dock.sh test</span> runs the test suite. The README section "Evidence and reproducibility" and <span className="font-mono text-xs text-text">docs/DEVELOPMENT_LOG.md</span> list every claim and how to check it.</li>
        </ol>
        <p className="mt-3 text-xs text-dim">If the backend is offline, Verify and Re-run say so and show the terminal command; they never show a result that was not computed.</p>
      </div>

      <div className="panel mt-10 rounded p-5">
        <h2 className="font-display">How to read this site</h2>
        <ul className="mt-2 space-y-1 text-sm text-dim">
          <li><b className="text-text">OFFICIAL</b> means a pre-registered run on single-use held-out seeds. <b className="text-text">REHEARSAL</b> means the verification used a separate rehearsal seed block.</li>
          <li><b className="text-text">PIPELINE V1 / V2</b> are two frozen versions of the pipeline; the official batch used v2.</li>
          <li><b className="text-text">SKIPPED</b> on a check means an earlier check failed, so the single-use held-out set was not spent. <b className="text-text">NOT RUN</b> means the check could not run.</li>
          <li>Everything on this site is read from recorded files. Nothing is computed live, and no model is called from this page.</li>
        </ul>
      </div>
    </div>
  )
}
