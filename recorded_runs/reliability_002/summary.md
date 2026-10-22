# reliability_002: REHEARSAL STUDY, NOT AN OFFICIAL RESULT (pipeline v2)

Completed 2026-10-22 14:07. All planned runs executed. Master seeds fixed in advance; no run re-rolled for its verdict. LocalRunner (labelled fallback, not Nebius). Rehearsal seed blocks only; held-out seeds were never run.

Runs: 8. Verdicts: {'VERIFIED': 4, 'FAILED': 3, 'UNVERIFIED': 0, 'ERROR (no verdict)': 1}. **VERIFIED rate: 4/8 = 50.0% (Wilson 95% [21.5%, 78.5%])**. Attempts needed (runs with a verdict): {1: 6, 3: 1}. Generator sources: {'llm': 8}.

## Side by side with pipeline v1 (reliability_001)

| | v1 (5 runs) | v2 (8 runs) |
|---|---|---|
| VERIFIED | 1/5 = 20% (Wilson 95% [4%, 62%]) | 4/8 = 50% ([22%, 78%]) |
| FAILED | 2 | 3 |
| UNVERIFIED | 0 | 0 |
| no verdict (error) | 2 | 1 |
| median est. cost per run | $0.029 | $0.032 |

Small samples: the intervals overlap heavily unless the difference is large. Different master seeds and rehearsal blocks in each study.

## Runs

| Run | Seed | Verdict | Attempts | Dev-stage checks failed, per attempt | Final G1-G6 | Generator | Analysis pass before -> after | Verification pass before -> after | Tokens (p/c) | Wall s (LLM s) | Est. cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| run_01_seed611 | 611 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (2 dropped, 0 clamped) | 72.8% [67.0%, 77.9%] -> 96.0% [92.8%, 97.8%] | 71.2% [66.6%, 75.5%] -> 95.8% [93.3%, 97.3%] | 8847/7239 | 124.06 (29.06) | 0.028868 |
| run_02_seed622 | 622 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (4 dropped, 0 clamped) | 77.2% [71.6%, 82.0%] -> 94.8% [91.3%, 96.9%] | 68.8% [64.0%, 73.1%] -> 95.8% [93.3%, 97.3%] | 10437/7847 | 143.63 (34.97) | 0.028465 |
| run_03_seed633 | 633 | FAILED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=fail G6=pass | llm `nemotron-3-super-120b-a12b` (1 dropped, 0 clamped) | 54.4% [48.2%, 60.5%] -> 82.8% [77.6%, 87.0%] | 72.0% [67.4%, 76.2%] -> 88.5% [85.0%, 91.3%] | 11101/10352 | 150.7 (38.98) | 0.03655 |
| run_04_seed644 | 644 | FAILED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=fail G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (2 dropped, 0 clamped) | 56.0% [49.8%, 62.0%] -> 85.6% [80.7%, 89.4%] | 72.5% [67.9%, 76.6%] -> 89.8% [86.4%, 92.3%] | 9048/7721 | 132.86 (26.06) | 0.030477 |
| run_05_seed655 | 655 | FAILED | 3 | [['G3'], ['G3'], ['G3']] | G1=pass G2=pass G3=fail G4=pass G5=skipped G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (4 dropped, 0 clamped) | 70.8% [64.9%, 76.1%] -> 88.0% [83.4%, 91.5%] | n/a -> n/a | 14284/19372 | 231.49 (64.56) | 0.070119 |
| run_06_seed666 | 666 | ERROR: LLMValidationError: analyst: output failed validation after retry: 4 v | 0 | [] | n/a | llm `nemotron-3-super-120b-a12b` (0 dropped, 0 clamped) | n/a -> n/a | n/a -> n/a | 16930/10045 | 47.37 (37.42) | 0.041558 |
| run_07_seed677 | 677 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `nemotron-3-super-120b-a12b` (1 dropped, 0 clamped) | 56.8% [50.6%, 62.8%] -> 96.0% [92.8%, 97.8%] | 69.8% [65.1%, 74.1%] -> 95.0% [92.4%, 96.7%] | 11249/9601 | 149.08 (37.53) | 0.033491 |
| run_08_seed688 | 688 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (3 dropped, 0 clamped) | 66.4% [60.3%, 72.0%] -> 96.0% [92.8%, 97.8%] | 68.0% [63.3%, 72.4%] -> 95.5% [93.0%, 97.1%] | 9126/7143 | 130.62 (25.46) | 0.02836 |

Pass rates are shown with Wilson 95% intervals. Cost is an ESTIMATE (tokens x the per-token prices the API reports); actual billing UNCONFIRMED.

## Min / median / max

- total_tokens: {'min': 16086, 'median': 19567.0, 'max': 33656, 'n': 8}
- wall_clock_total_s: {'min': 47.37, 'median': 138.245, 'max': 231.49, 'n': 8}
- llm_seconds: {'min': 25.46, 'median': 36.195, 'max': 64.56, 'n': 8}
- estimated_cost_usd: {'min': 0.02836, 'median': 0.031984, 'max': 0.070119, 'n': 8}
- total estimated cost of the study: $0.2979

## Does the model add value in scenario generation? (baseline failure rate, default policy)

- coverage scenarios: 337/1200 fail = 0.2808 (Wilson95 [0.2561, 0.3069])
- model-targeted scenarios: 369/800 fail = 0.4612 (Wilson95 [0.427, 0.4959])
- Pooled over the runs that produced a baseline. Region rationales from the model are unverified opinions; only these code-computed rates are evidence.

## Appendix: candidate tables (what the model proposed and what code measured)

### run_01_seed611 (seed 611): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 1.0}` | 5/56 | 0/182 | 0.748 | {'H1': '3/19', 'H2': '0/28', 'H3': '3/24', 'H4': '1/17'} |  |  |
| 1 | `{"grip_force": 70.0}` | 21/56 | 2/182 | 0.804 | {'H1': '1/19', 'H2': '20/28', 'H3': '3/24', 'H4': '14/17'} |  |  |
| 2 | `{"grip_force": 40.0, "retry_count": 2.0, "lift_speed": 0.15}` | 49/56 | 1/182 | 0.96 | {'H1': '19/19', 'H2': '27/28', 'H3': '17/24', 'H4': '16/17'} | **yes** |  |
| 3 | `{"grasp_hold_steps": 60.0, "lift_speed": 0.2}` | 13/56 | 3/182 | 0.768 | {'H1': '12/19', 'H2': '4/28', 'H3': '2/24', 'H4': '1/17'} |  |  |

### run_02_seed622 (seed 622): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 10/32 | 0/193 | 0.86 | {'H1': '2/14', 'H2': '5/10', 'H3': '2/11', 'H4': '7/16'} |  |  |
| 1 | `{"grip_force": 40.0, "retry_count": 2.0, "lift_speed": 0.1}` | 25/32 | 0/193 | 0.948 | {'H1': '12/14', 'H2': '7/10', 'H3': '9/11', 'H4': '14/16'} | **yes** |  |
| 2 | `{"grip_force": 80.0, "grasp_hold_steps": 120.0}` | 18/32 | 8/193 | 0.844 | {'H1': '11/14', 'H2': '2/10', 'H3': '9/11', 'H4': '7/16'} |  |  |
| 3 | `{"grip_force": 25.0, "grasp_hold_steps": 30.0, "retry_count": 1.0, "lift_speed": 0.25}` | 19/32 | 0/193 | 0.888 | {'H1': '10/14', 'H2': '5/10', 'H3': '8/11', 'H4': '10/16'} |  |  |

### run_03_seed633 (seed 633): generator `llm` / `nvidia/nemotron-3-super-120b-a12b`, verdict FAILED

**Attempt 1** (regression budget 2, selected candidate 3)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 7/83 | 0/136 | 0.644 | {'H1': '2/57', 'H2': '2/27', 'H3': '4/26'} |  |  |
| 1 | `{"grip_force": 30.0, "grasp_hold_steps": 30.0, "retry_count": 1.0}` | 57/83 | 0/136 | 0.816 | {'H1': '35/57', 'H2': '26/27', 'H3': '21/26'} |  |  |
| 2 | `{"grip_force": 20.0, "grasp_hold_steps": 15.0, "lift_speed": 0.25}` | 33/83 | 1/136 | 0.688 | {'H1': '18/57', 'H2': '19/27', 'H3': '14/26'} |  |  |
| 3 | `{"grip_force": 40.0, "lift_speed": 0.1, "lift_height": 0.2}` | 64/83 | 1/136 | 0.828 | {'H1': '44/57', 'H2': '26/27', 'H3': '19/26'} | **yes** |  |

### run_04_seed644 (seed 644): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict FAILED

**Attempt 1** (regression budget 2, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 11/69 | 0/140 | 0.708 | {'H1': '5/34', 'H2': '3/23', 'H3': '3/22', 'H4': '6/39'} |  |  |
| 1 | `{"grip_force": 40.0, "grasp_hold_steps": 30.0, "retry_count": 1.0, "lift_speed": 0.2}` | 55/69 | 1/140 | 0.856 | {'H1': '26/34', 'H2': '21/23', 'H3': '18/22', 'H4': '30/39'} | **yes** |  |
| 2 | `{"grip_force": 20.0, "grasp_hold_steps": 15.0, "retry_count": 1.0, "lift_speed": 0.28}` | 36/69 | 1/140 | 0.768 | {'H1': '18/34', 'H2': '9/23', 'H3': '13/22', 'H4': '21/39'} |  |  |
| 3 | `{"grip_force": 60.0, "retry_count": 1.0, "lift_speed": 0.1}` | 55/69 | 3/140 | 0.844 | {'H1': '26/34', 'H2': '21/23', 'H3': '18/22', 'H4': '30/39'} |  |  |

### run_05_seed655 (seed 655): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict FAILED

**Attempt 1** (regression budget 3, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 16/67 | 0/177 | 0.784 | {'H1': '4/41', 'H2': '15/38', 'H3': '4/17', 'H4': '4/36'} |  |  |
| 1 | `{"grip_force": 40.0}` | 29/67 | 2/177 | 0.82 | {'H1': '25/41', 'H2': '11/38', 'H3': '4/17', 'H4': '20/36'} | **yes** |  |
| 2 | `{"grip_force": 25.0, "grasp_hold_steps": 20.0, "lift_speed": 0.25}` | 22/67 | 0/177 | 0.812 | {'H1': '14/41', 'H2': '9/38', 'H3': '5/17', 'H4': '15/36'} |  |  |
| 3 | `{"grasp_hold_steps": 60.0, "lift_speed": 0.1}` | 11/67 | 4/177 | 0.752 | {'H1': '4/41', 'H2': '7/38', 'H3': '4/17', 'H4': '7/36'} |  |  |

**Attempt 2** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 16/67 | 0/177 | 0.784 | {'H1': '4/41', 'H2': '15/38', 'H3': '4/17', 'H4': '4/36'} |  |  |
| 1 | `{"grip_force": 60.0, "grasp_hold_steps": 30.0, "lift_speed": 0.2}` | 41/67 | 0/177 | 0.888 | {'H1': '33/41', 'H2': '15/38', 'H3': '8/17', 'H4': '28/36'} |  |  |
| 2 | `{"grip_force": 45.0, "grasp_hold_steps": 15.0, "retry_count": 1.0}` | 44/67 | 1/177 | 0.896 | {'H1': '30/41', 'H2': '19/38', 'H3': '10/17', 'H4': '26/36'} | **yes** |  |
| 3 | `{"grasp_hold_steps": 60.0, "lift_speed": 0.1}` | 11/67 | 4/177 | 0.752 | {'H1': '4/41', 'H2': '7/38', 'H3': '4/17', 'H4': '7/36'} |  |  |

**Attempt 3** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"grip_force": 70.0}` | 35/67 | 1/177 | 0.848 | {'H1': '31/41', 'H2': '13/38', 'H3': '4/17', 'H4': '25/36'} |  |  |
| 1 | `{"grasp_hold_steps": 30.0, "retry_count": 3.0, "lift_speed": 0.15}` | 28/67 | 1/177 | 0.84 | {'H1': '9/41', 'H2': '23/38', 'H3': '9/17', 'H4': '11/36'} |  |  |
| 2 | `{"grip_force": 50.0, "grasp_hold_steps": 20.0}` | 39/67 | 0/177 | 0.88 | {'H1': '31/41', 'H2': '14/38', 'H3': '8/17', 'H4': '26/36'} | **yes** |  |
| 3 | `{"grasp_hold_steps": 60.0}` | 8/67 | 7/177 | 0.728 | {'H1': '2/41', 'H2': '5/38', 'H3': '4/17', 'H4': '4/36'} |  |  |

### run_06_seed666 (seed 666): generator `llm` / `nvidia/nemotron-3-super-120b-a12b`, verdict None

_no fixer attempts (the run ended before the fixer)_

### run_07_seed677 (seed 677): generator `llm` / `nvidia/nemotron-3-super-120b-a12b`, verdict VERIFIED

**Attempt 1** (regression budget 2, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 6/94 | 0/142 | 0.628 | {'H1': '2/62', 'H2': '1/27', 'H3': '6/41', 'H4': '0/24'} |  |  |
| 1 | `{"grip_force": 40.0, "grasp_hold_steps": 60.0, "retry_count": 3.0}` | 87/94 | 0/142 | 0.96 | {'H1': '56/62', 'H2': '27/27', 'H3': '37/41', 'H4': '23/24'} | **yes** |  |
| 2 | `{"grip_force": 30.0, "lift_speed": 0.1}` | 62/94 | 1/142 | 0.824 | {'H1': '41/62', 'H2': '20/27', 'H3': '18/41', 'H4': '17/24'} |  |  |
| 3 | `{"grasp_hold_steps": 30.0, "retry_count": 1.0}` | 26/94 | 1/142 | 0.68 | {'H1': '2/62', 'H2': '20/27', 'H3': '6/41', 'H4': '8/24'} |  |  |

### run_08_seed688 (seed 688): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"grip_force": 70.0}` | 30/63 | 2/166 | 0.784 | {'H1': '26/36', 'H2': '2/22', 'H3': '5/18', 'H4': '23/33'} |  |  |
| 1 | `{"lift_speed": 0.25}` | 11/63 | 3/166 | 0.716 | {'H1': '2/36', 'H2': '7/22', 'H3': '2/18', 'H4': '3/33'} |  |  |
| 2 | `{"grip_force": 40.0, "retry_count": 2.0, "lift_speed": 0.15}` | 58/63 | 0/166 | 0.96 | {'H1': '32/36', 'H2': '22/22', 'H3': '15/18', 'H4': '31/33'} | **yes** |  |
| 3 | `{"grip_force": 25.0, "grasp_hold_steps": 20.0, "retry_count": 1.0, "lift_speed": 0.25}` | 44/63 | 1/166 | 0.868 | {'H1': '22/36', 'H2': '21/22', 'H3': '13/18', 'H4': '21/33'} |  |  |
