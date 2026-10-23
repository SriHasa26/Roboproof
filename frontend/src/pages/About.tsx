import { ReactNode } from 'react'
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
