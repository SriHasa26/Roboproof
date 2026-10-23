import { ReactNode, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Check } from '../lib'
import { Chip, checkLine } from '../ui'
import { useMotionPrefs } from '../motion'
import { Attempt, STAGES, StageState } from './derive'
import type { LiveEvent } from './api'

const COLOR: Record<StageState, string> = { pending: '#3a4540', active: '#f2b134', done: '#5be39a', error: '#ff6a47' }

export function Timeline({ stages }: { stages: Record<string, StageState> }) {
  return (
    <ol className="glass grid gap-0 p-4 sm:grid-cols-7 sm:p-5" aria-label="Pipeline stages">
      {STAGES.map(([k, name, sub], i) => {
        const s = stages[k]
        return (
          <li key={k} className="relative flex items-center gap-3 py-2 sm:flex-col sm:items-start sm:gap-2 sm:py-0 sm:pr-3">
            <div className="flex w-full items-center">
              <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full border-2 transition-colors duration-500" style={{ borderColor: COLOR[s], background: s === 'done' ? `${COLOR[s]}22` : 'transparent' }}>
                {s === 'active' && <span className="absolute inset-0 animate-ping rounded-full border-2 border-amber/60" aria-hidden />}
                {s === 'done' && <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#5be39a" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d="M5 12l5 5 9-10" /></svg>}
                {s === 'error' && <span className="text-xs font-bold text-verm" aria-hidden>!</span>}
                {(s === 'pending' || s === 'active') && <span className="font-mono text-[10px]" style={{ color: COLOR[s] }}>{i + 1}</span>}
              </span>
              {i < STAGES.length - 1 && <span className="ml-2 hidden h-0.5 flex-1 rounded sm:block" style={{ background: `linear-gradient(90deg, ${COLOR[s]}, ${COLOR[stages[STAGES[i + 1][0]]]})`, opacity: s === 'pending' ? 0.3 : 0.8 }} aria-hidden />}
            </div>
            <div>
              <div className={`font-display text-base font-bold ${s === 'pending' ? 'text-dim' : 'text-text'}`}>{name}<span className="sr-only"> ({s})</span></div>
              <div className="hidden text-[11px] leading-snug text-dim sm:block">{sub}</div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

const stageColor: Record<string, string> = { generator: 'text-ice', baseline: 'text-phos', evidence: 'text-phos', analyst: 'text-amber', fixer: 'text-amber', gate: 'text-phos', verdict: 'text-phos', run: 'text-dim', log: 'text-dim', end: 'text-dim' }

export function Terminal({ events }: { events: LiveEvent[] }) {
  const box = useRef<HTMLDivElement>(null)
  const stick = useRef(true)
  useEffect(() => { const el = box.current; if (el && stick.current) el.scrollTop = el.scrollHeight }, [events.length])
  const t0 = events.length ? Date.parse(events[0].time) : 0
  return (
    <div className="glass overflow-hidden">
      <div className="flex items-center gap-2 border-b hair px-4 py-2"><span className="h-2.5 w-2.5 rounded-full bg-verm/70" /><span className="h-2.5 w-2.5 rounded-full bg-amber/70" /><span className="h-2.5 w-2.5 rounded-full bg-phos/70" />
        <span className="ml-2 font-mono text-[11px] text-dim">pipeline log ({events.length} events)</span></div>
      <div ref={box} onScroll={(e) => { const el = e.currentTarget; stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40 }}
        className="h-64 overflow-y-auto p-4 font-mono text-[12px] leading-relaxed" role="log" aria-live="off" tabIndex={0}>
        {events.length === 0 && <span className="text-dim">waiting for the first event...</span>}
        {events.filter((e) => e.stage !== 'end').map((e) => (
          <div key={e.seq} className="flex gap-3">
            <span className="w-14 shrink-0 text-right text-dim tick">+{((Date.parse(e.time) - t0) / 1000).toFixed(1)}s</span>
            <span className={`w-16 shrink-0 ${stageColor[e.stage] ?? 'text-dim'}`}>{e.stage}</span>
            <span className={`min-w-0 break-words ${e.status === 'error' ? 'text-verm' : 'text-text/90'}`}>{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function Candidates({ attempts }: { attempts: Attempt[] }) {
  if (!attempts.length) return null
  return (
    <div className="space-y-4">
      {attempts.map((a) => (
        <motion.div key={a.attempt} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} className="glass overflow-x-auto p-4">
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h3 className="font-display">Attempt {a.attempt}: candidates measured by code</h3>
            <span className="font-mono text-[11px] text-dim">regression budget {a.regression_budget ?? 'n/a'}</span></div>
          <table className="w-full min-w-[560px] text-left font-mono text-[12px]">
            <thead className="text-[11px] uppercase text-dim"><tr><th className="py-1">#</th><th>Changes</th><th>Fixed</th><th>Regressions</th><th>Pass rate</th><th /></tr></thead>
            <tbody>
              {a.candidates.map((c, i) => (
                <motion.tr key={c.index} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.12 * i }} className={`border-t hair ${c.selected ? 'bg-amber/10' : ''}`}>
                  <td className="py-1.5">{c.index}</td>
                  <td>{Object.entries(c.applied ?? {}).map(([k, x]) => `${k} ${x}`).join(', ') || 'none'}</td>
                  <td className="tick">{c.fixed ?? '-'}/{c.targeted ?? '-'}</td><td className="tick">{c.regressions ?? '-'}</td>
                  <td className="tick">{c.pass_rate != null ? `${(c.pass_rate * 100).toFixed(1)}%` : 'n/a'}</td>
                  <td>{c.selected && <span className="rounded-sm bg-amber px-1.5 py-0.5 text-[10px] font-bold text-ink">SELECTED</span>}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-dim">{a.selection_rule}</p>
        </motion.div>
      ))}
    </div>
  )
}

const NAMES: Record<string, string> = { G1: 'Determinism', G2: 'Reproduced', G3: 'Fixed', G4: 'No regressions', G5: 'Held-out generalization', G6: 'Complete execution' }

/** The six checks light up one after another. The pipeline reports them together at the end of a run; the stagger is only presentation. */
export function GateLights({ gates, done }: { gates: Check[]; done: boolean }) {
  const { reduce } = useMotionPrefs()
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (reduce) { setShown(gates.length); return }
    if (shown >= gates.length) return
    const t = setTimeout(() => setShown((n) => n + 1), 380)
    return () => clearTimeout(t)
  }, [gates.length, shown, reduce])
  return (
    <ol className="glass divide-y divide-white/[.06]">
      {['G1', 'G2', 'G3', 'G4', 'G5', 'G6'].map((id, i) => {
        const c = i < shown ? gates.find((g) => g.id === id) : undefined
        return (
          <li key={id} className="flex flex-wrap items-center gap-3 p-3.5">
            <span className="w-9 font-display text-xl font-bold text-amber">{id}</span>
            {c ? <motion.span initial={{ scale: 0.7, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}><Chip status={c.status} /></motion.span>
              : <span className="inline-block rounded-sm border border-white/10 px-2 py-0.5 font-mono text-[11px] tracking-widest text-dim">{done ? 'NOT REPORTED' : 'WAITING'}</span>}
            <span className="min-w-0 flex-1 text-sm">{NAMES[id]}</span>
            {c && <p className="w-full pl-12 font-mono text-[11px] leading-relaxed text-dim">{checkLine(c)}</p>}
          </li>
        )
      })}
    </ol>
  )
}

export function Confirm({ title, children, confirm, onConfirm, onCancel, busy }: { title: string; children: ReactNode; confirm: string; onConfirm: () => void; onCancel: () => void; busy?: boolean }) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    ref.current?.focus()
    const f = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [onCancel])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={title} onClick={onCancel}>
      <motion.div initial={{ opacity: 0, scale: 0.96, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} className="glass w-full max-w-lg p-6" onClick={(e) => e.stopPropagation()}>
        <h2 className="font-display">{title}</h2>
        <div className="mt-3 space-y-3 text-sm leading-relaxed text-dim">{children}</div>
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <button className="btn btn-ghost" onClick={onCancel}>Cancel</button>
          <button ref={ref} className="btn btn-primary" onClick={onConfirm} disabled={busy}>{confirm}</button>
        </div>
      </motion.div>
    </div>
  )
}
