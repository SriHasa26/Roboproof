# Ceiling search (P3 Part B)

Goal: find out how high the pass rate can go by changing only the five patchable parameters, so the gate's held-out target comes from data. Dev seeds only; held-out seeds were not run. The simulator and default policy were not changed.

Script: `scripts/ceiling_search.py` (raw log: `docs/ceiling_search_results.json`), `scripts/ceiling_remaining.py` (remaining failures).

## Method

- Parameters searched: `grip_force`, `grasp_hold_steps`, `retry_count`, `lift_speed`, `lift_height`, each within its frozen bounds.
- Search: the default policy, 6 hand-picked anchors, 40 uniform random policies, then one round of coordinate refinement around the best. 71 distinct policies evaluated, each on 300 scenarios (25,500 simulations in total including cross-checks), 12 worker processes, 1833 s wall-clock on this machine.
- Selection used **dev set A** only (Latin hypercube, sweep seed 11, n=300, seeds from 1000). The default and the winner were then re-measured on **dev set B** (sweep seed 23, n=300, seeds from 50000, disjoint seeds).
- Caveat: the search is small and not exhaustive, so the true ceiling could be a little higher. The best policy was selected on set A, so set A's 96.7% is optimistically biased; set B is the honest number.

## Results

| Policy | Set A pass | Set B pass | Mean time of successes (A) |
|---|---|---|---|
| Default (grip 15, hold 10, retries 0, lift speed 0.3, lift height 0.15) | 72.0% | 71.7% | 3.65 s |
| Best found (grip 58.8, hold 86, retries 3, lift speed 0.59, lift height 0.119) | 96.7% | 98.0% | 3.83 s |

Distribution over the 71 searched policies (set A): median ~90%; 58 reached >=80%, 52 reached >=85%, 34 reached >=90%, 28 reached >=95%. Some combinations are bad (minimum 0%, from a lift height that hits the wall).

The next four best policies differ from the winner only in `grasp_hold_steps` or `lift_speed` and score 96.7% on set A and 97.3% to 97.7% on set B, so the plateau is flat, not a single lucky point.

**This means a fix is easy to find.** Most reasonable parameter increases help. The demo's "attempt 1 fails the gate, attempt 2 passes" story therefore cannot rely on the fix being hard; it has to come from a patch that is partial or has a side effect (see the scripted trap).

## Remaining failures under the best policy ("unfixable by these parameters")

Set A: 10 of 300 fail (MISSED_GRASP 5, COLLISION 3, PLACED_OUTSIDE_ZONE 2). Set B: 6 of 300 fail (MISSED_GRASP 3, PLACED_OUTSIDE_ZONE 3).

All 16 have sensor noise >= 0.018 m, and 14 of the 16 have noise >= 0.022 m (range of the axis: 0 to 0.03). With that much perception error the fingers land on the cube or grasp it off-centre, and retries re-draw the noise but only up to 3 times. Parameters cannot remove perception error. These are the failures the system should report honestly as not fixable by the allowed knobs.

## Proposed gate thresholds (`backend/app/core/gate_config.py`)

| Setting | Value | Why |
|---|---|---|
| `GATE_HELDOUT_TARGET` | 0.90 | Best found is 96.7% to 98.0%, so 0.90 leaves about 7 points of margin below the ceiling. The default sits at ~72%, so 0.90 demands a real fix. The brief's 0.80 default would be passed by 58 of 71 searched policies including mediocre ones, so it would not discriminate. |
| `GATE_MIN_IMPROVEMENT` | 0.10 | The patched held-out pass rate must also beat the unpatched policy's on the same held-out set by at least 10 points (absolute). |
| Wilson rule (unchanged) | lower 95% bound of patched > unpatched point estimate | From PROJECT_BRIEF.md section 3.3. |
| `GATE_HELDOUT_SIZE` | 400 | Wilson 95% half-width is about 0.03 at p=0.90. A policy at the ceiling (~97%) clears 0.90 comfortably; a policy near 90% passes only about half the time, which is the intended behaviour. |
| `GATE_REGRESSION_BUDGET` | 0 | The simulator is deterministic, so any scenario that passed before and now fails is a real regression. |

These are proposals. They were chosen from dev data only. If you want an easier demo, 0.85 is also defensible (52 of 71 searched policies reached it) but it would let weaker patches through.
