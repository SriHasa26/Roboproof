import { useEffect, useState } from 'react'
import { load, usd } from '../lib'
import { Skeleton } from '../motion'
import { SourceChip } from '../ui'

type Call = {
  n: number; stage: string | null; purpose: string | null; role: string | null; model_requested: string | null; model_returned: string | null; response_id: string | null
  started: string | null; ended: string | null; latency_s: number | null; prompt_tokens: number | null; completion_tokens: number | null; finish_reason: string | null
  reply_channel: string | null; cached: boolean | null; retry: number | null; ok: boolean | null; error: string | null
}
type Reply = { index: number; purpose: string | null; model: string | null; attempt: number | null; cached?: boolean | null; reply: string }
type Bundle = {
  calls: Call[]; replies?: Reply[]; source: string; note: string; in_progress?: boolean; response_metadata_captured?: boolean
  totals: { calls: number; prompt_tokens: number; completion_tokens: number; estimated_cost_usd: number | null; cost_note: string }
}

const NR = <span className="italic text-dim/70">not recorded</span>
const short = (m: string | null) => (m ? m.split('/').pop() : null)

export type CallsSrc = { file?: string; url?: string; repliesUrl?: string; origin: 'recorded' | 'live' | 'replay'; label: string }

/** The model calls of a run, straight from the stored artifacts (or the live API). Fields that were never recorded say so. */
export default function ModelCalls({ src }: { src: CallsSrc }) {
  const [b, setB] = useState<Bundle | null | undefined>(undefined)
  const [replies, setReplies] = useState<Reply[] | null>(null)
  useEffect(() => {
    setB(undefined); setReplies(null)
    const p: Promise<Bundle> = src.url ? fetch(src.url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status))))) : load<Bundle>(src.file ?? '')
    p.then((d) => { setB(d); if (d.replies) setReplies(d.replies) }).catch(() => setB(null))
    if (src.repliesUrl) fetch(src.repliesUrl).then((r) => (r.ok ? r.json() : null)).then((d) => d && Array.isArray(d.replies) && setReplies(d.replies)).catch(() => undefined)
  }, [src.file, src.url, src.repliesUrl])
  if (b === null) return null // no call log for this run: show nothing rather than invent one
  const download = () => {
    if (!b) return
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({ label: src.label, ...b, replies: undefined }, null, 1)], { type: 'application/json' })); a.download = `model_calls_${src.label.replace(/\W+/g, '_')}.json`; a.click(); URL.revokeObjectURL(a.href)
  }
  return (
    <section className="mb-14" aria-label="Model calls">
      <div className="eyebrow mb-1.5">the real Nebius calls</div>
      <h2 className="mb-3 text-3xl">Model calls</h2>
      <div className="mb-3 flex flex-wrap items-center gap-2"><SourceChip kind={src.origin} detail={src.origin === 'live' ? `captured at call time | ${src.label}` : src.origin === 'replay' ? `recorded live run | ${src.label}` : `stored artifact | ${src.label}`} />{b && <button className="chip hover:!border-amber/60 hover:!text-text" onClick={download}>Download JSON</button>}</div>
      {b === undefined ? <Skeleton className="h-40" /> : (
        <>
          <p className="mb-3 font-mono text-xs text-dim tick">
            {b.totals.calls} calls | {b.totals.prompt_tokens.toLocaleString()} prompt + {b.totals.completion_tokens.toLocaleString()} completion tokens | estimated cost {usd(b.totals.estimated_cost_usd)} (estimate, billing not checked){b.in_progress ? ' | run in progress' : ''}
          </p>
          <div className="glass overflow-x-auto" tabIndex={0} role="region" aria-label="Model call table, scrolls sideways">
            <p className="sticky left-0 px-3 pt-2 text-[11px] text-dim lg:hidden">Swipe sideways for all columns: started time, finish reason, channel and the provider response id.</p>
            <table className="w-full min-w-[1100px] text-left text-xs [&_td]:px-2 [&_th]:px-2 [&_th]:py-2 [&_td]:py-2">
              <thead className="font-mono text-[10px] uppercase tracking-wider text-dim"><tr><th className="p-2.5">#</th><th>Stage</th><th>Role</th><th>Model (as returned by the API)</th><th>Started (UTC)</th><th>Latency</th><th>Tokens in / out</th><th>Finish</th><th>Channel</th><th>Cached</th><th>Retry</th><th>Provider response id</th></tr></thead>
              <tbody>
                {b.calls.map((c) => (
                  <tr key={c.n} className="border-t hair align-top">
                    <td className="p-2.5 font-mono">{c.n}</td>
                    <td>{c.stage ?? NR}{c.ok === false && <span className="ml-1 text-verm" title={c.error ?? ''}>rejected</span>}</td>
                    <td className="font-mono">{c.role ?? NR}</td>
                    <td className="font-mono">{c.model_returned ? short(c.model_returned) : <>{short(c.model_requested)} <span className="text-dim">(requested; returned id {NR})</span></>}</td>
                    <td className="font-mono tick">{c.started ? c.started.replace('T', ' ').slice(0, 19) : NR}</td>
                    <td className="font-mono tick">{c.latency_s != null ? `${c.latency_s.toFixed(1)} s` : NR}</td>
                    <td className="font-mono tick">{c.prompt_tokens ?? '-'} / {c.completion_tokens ?? '-'}</td>
                    <td className="font-mono">{c.finish_reason ?? NR}</td>
                    <td className="font-mono">{c.reply_channel ?? NR}</td>
                    <td className="font-mono">{c.cached == null ? NR : c.cached ? 'yes' : 'no (real call)'}</td>
                    <td className="font-mono">{c.retry ?? NR}</td>
                    <td className="break-all pr-2 font-mono" title={c.response_id ?? ''}>{c.response_id ?? NR}</td>
                  </tr>))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-dim">{b.note} Source: {b.source}.</p>
          {replies && replies.length > 0 && (
            <div className="mt-5 space-y-2">
              <h3 className="font-display">Raw model replies <span className="ml-2 rounded-sm border border-amber/50 px-1.5 py-0.5 font-mono text-[10px] text-amber">model output, unverified</span></h3>
              {replies.map((r) => (
                <details key={r.index} className="glass px-4 py-2">
                  <summary className="cursor-pointer text-sm"><span className="font-mono text-xs text-dim">#{r.index}</span> {r.purpose ?? 'call'} <span className="font-mono text-xs text-dim">| {short(r.model) ?? 'model'} | try {r.attempt ?? '?'} | {r.reply.length.toLocaleString()} characters</span></summary>
                  <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-text/90">{r.reply}</pre>
                </details>))}
            </div>
          )}
        </>
      )}
    </section>
  )
}
