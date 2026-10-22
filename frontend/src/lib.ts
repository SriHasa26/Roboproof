import { useEffect, useState } from 'react'

export type Rate = { n: number; pass_rate: number; pass_rate_ci95: [number, number]; collision_rate: number; mean_completion_time_s: number | null }
export type Status = 'pass' | 'fail' | 'not_run' | 'skipped_after_failure'
export type Check = { id: string; name: string; status: Status; observed: Record<string, any>; threshold: Record<string, any>; details: string }
export type Cand = {
  index: number; applied: Record<string, number>; fixed: number | null; targeted: number | null; regressions: number | null
  previously_passing: number | null; pass_rate: number | null; per_hypothesis_fixed: Record<string, string>; selected: boolean; complete: boolean
  clamped: Record<string, boolean>; rounded: Record<string, number[]>
}
export type CandTable = {
  attempt: number; selected_index: number; regression_budget: number | null; v1_single_patch: boolean
  diversity_violations: string[]; dropped: { index: number; reason: string }[]; candidates: Cand[]
}
export type Evidence = { id: string; kind: string; title: string; data: Record<string, any> }
export type Hyp = {
  id: string; model_text_unverified: { statement: string; mechanism: string; prediction: string }
  region: Record<string, number[]>; levers: { param: string; direction: string }[]; targeted_failures: number; evidence: Evidence[]
}
export type Heat = { x: string; y: string; x_edges: number[]; y_edges: number[]; cells: { n: number; n_fail: number }[][] }
export type Badges = { pipeline_version: string; mode: 'official' | 'rehearsal'; runner: string; recorded: boolean }
export type Run = {
  id: string; badges: Badges; label: string | null; master_seed: number; verdict: 'VERIFIED' | 'FAILED' | 'UNVERIFIED'; error: string | null
  attempts_used: number; g5_executed: boolean
  gate: { checks: Check[]; regressed_scenario_ids: string[]; strict_zero_budget: { regressions: number | null; pass: boolean | null }; config: Record<string, any>; verification_set: Record<string, any> }
  metrics: { analysis?: { before: Rate; after?: Rate }; verification?: { before: Rate; after: Rate } }
  candidate_tables: CandTable[]; hypotheses: Hyp[]
  generator: {
    source: string; model: string | null; dropped_regions: { name: string; reason: string }[]; clamped_values: any[]; trail: Record<string, any>[]
    regions_used: { name: string; ranges: Record<string, number[]>; rationale_unverified: string }[]
  }
  heatmaps: Heat[]; analysis_set: { n: number; n_coverage: number; n_targeted: number }
  timing: { wall_clock_s: number; llm_s: number; candidate_evals_s: number; other_simulation_s: number }
  tokens: { prompt: number | null; completion: number | null; llm_calls: number | null }
  cost: { estimated_usd: number | null; note: string }
  provenance: Record<string, any>; final_patch: Record<string, number> | null
}
export type IndexItem = { id: string; badges: Badges; verdict: string; master_seed: number; attempts_used: number; generator_source: string }
export type Row = {
  run_id: string; master_seed: number; verdict: string | null; attempts: number | null; error: string | null
  analysis_before: Rate | null; analysis_after: Rate | null; verification_before: Rate | null; verification_after: Rate | null
  estimated_cost_usd: number | null; wall_clock_total_s: number | null; final_checks: Record<string, string> | null
  generator: { source: string | null; model: string | null } | null
}
export type Agg = {
  runs: number; verdict_counts: Record<string, number>; verified_rate: { verified: number; of_runs: number; rate: number; wilson95: [number, number] }
  attempts_distribution_for_runs_with_a_verdict: Record<string, number>; total_estimated_cost_usd: number
}
export type Summary = { pipeline_version: string; note: string; aggregate: Agg; runs: Row[] }
export type Study = { name: string; pipeline_version: string; note: string; aggregate: Agg; runs: Row[] }
export type Trap = {
  label: string; patch: Record<string, number>; patch_description: string; targeting: string; verdict: string; checks: Check[]
  metrics: Run['metrics']; regressed_scenario_ids: string[]; strict_zero_budget: { regressions: number | null; pass: boolean | null }; note: string
}
export type Replays = {
  run: string; scenario: Record<string, any>; seed: number; note: string
  baseline: { gif: string; result: Record<string, any>; policy: Record<string, number> }
  patched: { gif: string; result: Record<string, any>; policy: Record<string, number> }
} | null

export const dataUrl = (p: string) => `${import.meta.env.BASE_URL}data/${p}`
const cache = new Map<string, Promise<any>>()
export function load<T>(p: string): Promise<T> {
  if (!cache.has(p)) {
    cache.set(p, fetch(dataUrl(p)).then((r) => {
      if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`)
      return p.endsWith('.md') ? r.text() : r.json()
    }))
  }
  return cache.get(p) as Promise<T>
}
export function useData<T>(p: string): { data: T | null; error: string | null } {
  const [s, set] = useState<{ data: T | null; error: string | null }>({ data: null, error: null })
  useEffect(() => {
    let live = true
    set({ data: null, error: null })
    load<T>(p).then((d) => live && set({ data: d, error: null })).catch((e) => live && set({ data: null, error: String(e) }))
    return () => { live = false }
  }, [p])
  return s
}

export const pct = (x: number | null | undefined, d = 1) => (x == null ? 'n/a' : `${(x * 100).toFixed(d)}%`)
export const ci = (r: Rate | null | undefined) => (r ? `${pct(r.pass_rate)} [${pct(r.pass_rate_ci95[0], 0)} to ${pct(r.pass_rate_ci95[1], 0)}]` : 'n/a')
export const usd = (x: number | null | undefined) => (x == null ? 'n/a' : `$${x.toFixed(3)}`)
export const short = (m: string | null | undefined) => (m ? m.split('/').pop() : '-')
