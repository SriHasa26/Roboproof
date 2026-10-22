# official_001: OFFICIAL BATCH (pre-registered) (pipeline v2)

OFFICIAL BATCH per docs/OFFICIAL_PROTOCOL.md (protocol commit 8171c7d). All 5 pre-registered runs executed, none repeated, none discarded; G5 executed in every run. Run 1 is the headline run by rule. LocalRunner (local fallback, not Nebius). Each run used its own single-use held-out block (900000 to 901999); all marked used in the seed ledger.

Runs: 5. Verdicts: {'VERIFIED': 4, 'FAILED': 1, 'UNVERIFIED': 0, 'ERROR (no verdict)': 0}. **VERIFIED rate: 4/5 = 80.0% (Wilson 95% [37.6%, 96.4%])**. Attempts needed (runs with a verdict): {2: 2, 1: 3}. Generator sources: {'llm': 5}.

## Runs

| Run | Seed | Verdict | Attempts | Dev-stage checks failed, per attempt | Final G1-G6 | Generator | Analysis pass before -> after | Verification pass before -> after | Collision rate on verification set before -> after | Tokens (p/c) | Wall s (LLM s) | Est. cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| official_01_seed3101 | 3101 | VERIFIED | 2 | [['G3'], []] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (1 dropped, 0 clamped) | 72.4% [66.5%, 77.6%] -> 94.8% [91.3%, 96.9%] | 71.2% [66.6%, 75.5%] -> 96.8% [94.5%, 98.1%] | 0.8% -> 1.0% | 10834/10535 | 167.4 (36.24) | 0.040663 |
| official_02_seed3202 | 3202 | VERIFIED | 2 | [['G3'], []] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (1 dropped, 0 clamped) | 68.4% [62.4%, 73.9%] -> 90.4% [86.1%, 93.5%] | 68.8% [64.0%, 73.1%] -> 95.5% [93.0%, 97.1%] | 0.5% -> 1.5% | 11439/14914 | 193.07 (68.57) | 0.05488 |
| official_03_seed3303 | 3303 | FAILED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=fail G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (3 dropped, 0 clamped) | 70.8% [64.9%, 76.1%] -> 93.2% [89.4%, 95.7%] | 69.0% [64.3%, 73.3%] -> 87.0% [83.4%, 90.0%] | 0.5% -> 0.5% | 9218/7611 | 119.91 (28.23) | 0.029329 |
| official_04_seed3404 | 3404 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (0 dropped, 0 clamped) | 76.4% [70.8%, 81.2%] -> 96.8% [93.8%, 98.4%] | 69.2% [64.6%, 73.6%] -> 97.5% [95.5%, 98.6%] | 1.0% -> 1.0% | 8567/6612 | 108.88 (25.6) | 0.02607 |
| official_05_seed3505 | 3505 | VERIFIED | 1 | [[]] | G1=pass G2=pass G3=pass G4=pass G5=pass G6=pass | llm `NVIDIA-Nemotron-3-Nano-30B-A3B` (1 dropped, 0 clamped) | 65.2% [59.1%, 70.8%] -> 94.8% [91.3%, 96.9%] | 71.2% [66.6%, 75.5%] -> 96.8% [94.5%, 98.1%] | 1.0% -> 0.8% | 8925/7571 | 124.22 (31.99) | 0.030011 |

Pass rates are shown with Wilson 95% intervals. Cost is an ESTIMATE (tokens x the per-token prices the API reports); actual billing UNCONFIRMED.

## Min / median / max

- total_tokens: {'min': 15179, 'median': 16829, 'max': 26353, 'n': 5}
- wall_clock_total_s: {'min': 108.88, 'median': 124.22, 'max': 193.07, 'n': 5}
- llm_seconds: {'min': 25.6, 'median': 31.99, 'max': 68.57, 'n': 5}
- estimated_cost_usd: {'min': 0.02607, 'median': 0.030011, 'max': 0.05488, 'n': 5}
- total estimated cost of the study: $0.181

## Does the model add value in scenario generation? (baseline failure rate, default policy)

- coverage scenarios: 205/750 fail = 0.2733 (Wilson95 [0.2427, 0.3063])
- model-targeted scenarios: 162/500 fail = 0.324 (Wilson95 [0.2845, 0.3662])
- Pooled over the runs that produced a baseline. Region rationales from the model are unverified opinions; only these code-computed rates are evidence.

## Appendix: candidate tables (what the model proposed and what code measured)

### official_01_seed3101 (seed 3101): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 3)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"grip_force": 60.0}` | 10/50 | 0/181 | 0.804 | {'H1': '8/18', 'H2': '6/36', 'H3': '1/13'} |  |  |
| 1 | `{"retry_count": 1.0}` | 2/50 | 0/181 | 0.74 | {'H1': '1/18', 'H2': '2/36', 'H3': '0/13'} |  |  |
| 2 | `{"grip_force": 30.0, "grasp_hold_steps": 30.0, "lift_speed": 0.2}` | 22/50 | 0/181 | 0.864 | {'H1': '11/18', 'H2': '11/36', 'H3': '11/13'} |  |  |
| 3 | `{"grasp_hold_steps": 50.0, "retry_count": 2.0, "lift_height": 0.2}` | 28/50 | 0/181 | 0.884 | {'H1': '9/18', 'H2': '19/36', 'H3': '12/13'} | **yes** |  |

**Attempt 2** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"lift_speed": 0.1}` | 15/50 | 0/181 | 0.812 | {'H1': '5/18', 'H2': '7/36', 'H3': '10/13'} |  |  |
| 1 | `{"grip_force": 40.0, "retry_count": 2.0, "lift_speed": 0.2}` | 34/50 | 0/181 | 0.932 | {'H1': '16/18', 'H2': '21/36', 'H3': '12/13'} |  |  |
| 2 | `{"grip_force": 80.0, "grasp_hold_steps": 100.0, "retry_count": 3.0, "lift_speed": 0.05}` | 38/50 | 0/181 | 0.948 | {'H1': '17/18', 'H2': '24/36', 'H3': '13/13'} | **yes** |  |
| 3 | `{"grip_force": 20.0, "grasp_hold_steps": 15.0, "lift_speed": 0.25, "lift_height": 0.18}` | 12/50 | 1/181 | 0.808 | {'H1': '5/18', 'H2': '7/36', 'H3': '6/13'} |  |  |

### official_02_seed3202 (seed 3202): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 25/76 | 0/171 | 0.792 | {'H1': '10/35', 'H2': '5/26', 'H3': '20/55', 'H4': '13/42'} |  |  |
| 1 | `{"grip_force": 25.0, "grasp_hold_steps": 21.0, "lift_speed": 0.2}` | 24/76 | 0/171 | 0.784 | {'H1': '14/35', 'H2': '13/26', 'H3': '12/55', 'H4': '15/42'} |  |  |
| 2 | `{"grip_force": 40.0, "grasp_hold_steps": 60.0, "retry_count": 1.0}` | 38/76 | 1/171 | 0.836 | {'H1': '24/35', 'H2': '21/26', 'H3': '21/55', 'H4': '22/42'} | **yes** |  |
| 3 | `{"grasp_hold_steps": 60.0}` | 16/76 | 4/171 | 0.736 | {'H1': '6/35', 'H2': '11/26', 'H3': '8/55', 'H4': '12/42'} |  |  |

**Attempt 2** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 25/76 | 0/171 | 0.792 | {'H1': '10/35', 'H2': '5/26', 'H3': '20/55', 'H4': '13/42'} |  |  |
| 1 | `{"grip_force": 50.0, "grasp_hold_steps": 80.0, "lift_speed": 0.2}` | 32/76 | 2/171 | 0.808 | {'H1': '22/35', 'H2': '17/26', 'H3': '16/55', 'H4': '18/42'} |  |  |
| 2 | `{"grip_force": 80.0, "grasp_hold_steps": 120.0, "retry_count": 2.0}` | 55/76 | 3/171 | 0.904 | {'H1': '30/35', 'H2': '22/26', 'H3': '35/55', 'H4': '32/42'} | **yes** |  |
| 3 | `{"lift_speed": 0.1}` | 16/76 | 0/171 | 0.752 | {'H1': '6/35', 'H2': '11/26', 'H3': '8/55', 'H4': '12/42'} |  |  |

### official_03_seed3303 (seed 3303): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict FAILED

**Attempt 1** (regression budget 3, selected candidate 2)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 3/47 | 0/177 | 0.768 | {'H1': '0/26', 'H2': '0/13', 'H3': '3/14', 'H4': '0/27'} |  |  |
| 1 | `{"grip_force": 40.0, "grasp_hold_steps": 60.0, "lift_speed": 0.1}` | 33/47 | 0/177 | 0.904 | {'H1': '20/26', 'H2': '12/13', 'H3': '6/14', 'H4': '21/27'} |  |  |
| 2 | `{"grip_force": 80.0, "grasp_hold_steps": 30.0, "retry_count": 1.0, "lift_speed": 0.2}` | 37/47 | 0/177 | 0.932 | {'H1': '24/26', 'H2': '12/13', 'H3': '6/14', 'H4': '25/27'} | **yes** |  |
| 3 | `{"grip_force": 25.0, "grasp_hold_steps": 20.0, "retry_count": 1.0, "lift_speed": 0.25}` | 22/47 | 0/177 | 0.868 | {'H1': '11/26', 'H2': '9/13', 'H3': '2/14', 'H4': '12/27'} |  |  |

### official_04_seed3404 (seed 3404): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"retry_count": 3.0}` | 11/37 | 0/191 | 0.864 | {'H1': '1/17', 'H2': '4/16', 'H3': '6/15'} |  |  |
| 1 | `{"grip_force": 40.0, "grasp_hold_steps": 60.0, "retry_count": 3.0, "lift_speed": 0.1}` | 34/37 | 0/191 | 0.968 | {'H1': '14/17', 'H2': '15/16', 'H3': '14/15'} | **yes** |  |
| 2 | `{"grip_force": 80.0, "grasp_hold_steps": 120.0}` | 27/37 | 4/191 | 0.876 | {'H1': '14/17', 'H2': '14/16', 'H3': '6/15'} |  |  |
| 3 | `{"grip_force": 25.0, "grasp_hold_steps": 20.0, "retry_count": 1.0, "lift_speed": 0.25}` | 23/37 | 0/191 | 0.884 | {'H1': '9/17', 'H2': '13/16', 'H3': '7/15'} |  |  |

### official_05_seed3505 (seed 3505): generator `llm` / `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, verdict VERIFIED

**Attempt 1** (regression budget 3, selected candidate 1)

| # | Applied changes | Fixed | Regressions | Pass | Per hypothesis | Selected | Clamped / rounded |
|---|---|---|---|---|---|---|---|
| 0 | `{"grip_force": 25.0}` | 14/70 | 1/163 | 0.704 | {'H1': '12/44', 'H2': '0/17', 'H3': '4/21', 'H4': '12/45'} |  |  |
| 1 | `{"grip_force": 55.0, "grasp_hold_steps": 90.0, "retry_count": 3.0, "lift_speed": 0.1}` | 62/70 | 1/163 | 0.948 | {'H1': '39/44', 'H2': '17/17', 'H3': '18/21', 'H4': '41/45'} | **yes** |  |
| 2 | `{"grip_force": 20.0, "grasp_hold_steps": 20.0, "retry_count": 1.0, "lift_speed": 0.25, "lift_height": 0.18}` | 35/70 | 0/163 | 0.8 | {'H1': '22/44', 'H2': '13/17', 'H3': '11/21', 'H4': '20/45'} |  |  |
| 3 | `{"lift_height": 0.25}` | 0/70 | 0/163 | 0.652 | {'H1': '0/44', 'H2': '0/17', 'H3': '0/21', 'H4': '0/45'} |  |  |
