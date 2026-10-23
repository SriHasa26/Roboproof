import type { Check, Rate } from '../lib'
import type { LiveEvent } from './api'

export const STAGES: [string, string, string][] = [
  ['generator', 'Generate', 'Nemotron Nano proposes regions; code adds coverage'],
  ['baseline', 'Simulate', 'PyBullet runs the unpatched policy'],
  ['evidence', 'Evidence', 'Failure statistics computed in code'],
  ['analyst', 'Analyze', 'Nemotron Ultra writes hypotheses'],
  ['fixer', 'Fix', 'Ultra proposes; code measures every candidate'],
  ['gate', 'Prove', 'Deterministic gate G1 to G6'],
  ['verdict', 'Verdict', 'VERIFIED, FAILED or UNVERIFIED'],
]
export type StageState = 'pending' | 'active' | 'done' | 'error'
export type Attempt = { attempt: number; selected_index: number; regression_budget: number | null; selection_rule: string; candidates: any[]; dev_stage_passed: boolean | null }
export type View = {
  stages: Record<string, StageState>; attempts: Attempt[]; gates: Check[]; metrics: { analysis?: { before: Rate; after?: Rate }; verification?: { before: Rate; after: Rate } } | null
  strictZero: { regressions: number | null; pass: boolean | null } | null
  verdict: string | null; finalStatus: string | null; finalMessage: string | null; ended: boolean; costUsd: number | null
  masterSeed: number | null; elapsedS: number; llmCalls: number; tokens: number
}

export function derive(events: LiveEvent[]): View {
  const stages: Record<string, StageState> = Object.fromEntries(STAGES.map(([k]) => [k, 'pending' as StageState]))
  const v: View = { stages, attempts: [], gates: [], metrics: null, strictZero: null, verdict: null, finalStatus: null, finalMessage: null, ended: false, costUsd: null, masterSeed: null, elapsedS: 0, llmCalls: 0, tokens: 0 }
  for (const e of events) {
    const d = e.data ?? {}
    if (e.stage in stages) {
      if (e.status === 'start' && stages[e.stage] === 'pending') stages[e.stage] = 'active'
      if (e.status === 'done' && e.stage !== 'verdict') stages[e.stage] = 'done'
    }
    if (e.stage === 'fixer' && e.status === 'start' && stages.gate === 'pending') stages.gate = 'active'
    if (e.stage === 'fixer' && e.status === 'done' && d.candidates) v.attempts.push(d as Attempt)
    if (e.stage === 'gate' && d.check) v.gates.push(d.check as Check)
    if (e.stage === 'gate' && d.metrics) { v.metrics = d.metrics; v.strictZero = d.strict_zero_budget ?? null }
    if (d.master_seed != null && v.masterSeed == null) v.masterSeed = d.master_seed
    if (d.purpose) { v.llmCalls += 1; v.tokens += (d.prompt_tokens ?? 0) + (d.completion_tokens ?? 0) }
    if (d.final_status) {
      v.finalStatus = d.final_status; v.finalMessage = e.message; v.verdict = d.verdict ?? null; v.costUsd = d.estimated_cost_usd ?? null
      if (d.final_status === 'finished' && d.verdict) { for (const k of Object.keys(stages)) stages[k] = 'done' } else { for (const k of Object.keys(stages)) if (stages[k] === 'active') stages[k] = 'error' }
    }
    if (e.stage === 'end') v.ended = true
  }
  if (events.length > 1) v.elapsedS = Math.max(0, (Date.parse(events[events.length - 1].time) - Date.parse(events[0].time)) / 1000)
  return v
}
