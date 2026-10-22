# Feedback on Nebius Token Factory, Nebius AI Cloud docs and NVIDIA Nemotron models

Factual notes from building RoboProof, each dated and tied to evidence in this repository. Everything here was measured or read on the date given; nothing is praise or complaint we did not observe. Where something is a documentation reading only (we did not run it), it says so. Times are local (IST). Costs are estimates from the per-token prices the API itself reports.

## Nebius Token Factory

### Availability: the Nano chat endpoint hung for at least 39 minutes (2026-10-22)
- **Observed:** `POST /v1/chat/completions` for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` connected (TCP connect about 0.3 s) but returned no first byte; client timeouts and "Connection error" at 40 to 180 s. First failing probe finished about 17:28 (it had started about 17:20); a 12-attempt poll from 17:40:57 saw HTTP 000 after 40 s eleven times; it answered at 17:59:07 with a first byte after 22 s for a trivial prompt, then normal speed (0.9 s) by 18:08.
- **At the same time** `GET /v1/models` was instant, and `nvidia/Nemotron-3-Ultra-550b-a55b` (1.07 s), `nvidia/Nemotron-3_5-Lightning` (1.10 s) and `nvidia/nemotron-3-super-120b-a12b` (1.11 s) answered a trivial prompt normally with the same key (raw curl timings, printed during the session, not saved to a file).
- **We cannot say why** (UNCONFIRMED; no status information was available to us). We observed at least about 39 minutes (17:20 to 17:59); it may have started earlier.
- **Evidence:** `docs/evidence/fast_model_outage_poll_2026-10-22.log`, `docs/reasoning_control_probe_attempt1_infra_failure.json`, `docs/reasoning_control_probe_attempt2_infra_failure.json`.
- **What we did about it:** a per-call timeout (60 s), zero transport retries for the generator, and a fallback chain (another Nemotron model, then a code-made coverage-only set) in pipeline v2.

### `reasoning_effort="none"` returned an empty `content` on the Nano
- The chat-completion API reference lists `reasoning_effort` with values none, minimal, low, medium, high, xhigh, max, and does not say which models honour it ([API reference](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion), read 2026-10-22).
- On the Nano with `reasoning_effort="none"` the request was accepted (HTTP 200, `finish_reason: stop`), 523 completion tokens, but `content` was empty and the reply sat in a non-standard `reasoning` message field (1,284 characters). We could not use the response.
- **Evidence:** `docs/reasoning_control_probe.json` (variant `reasoning_effort_none`), `docs/reasoning_control_probe2.json` (`A_reasoning_effort_none_fields`).

### `enable_thinking: false` via `extra_body.chat_template_kwargs` works but is not documented by Nebius
- NVIDIA's model card documents `enable_thinking=False` as a chat-template switch for Nemotron 3. The Nebius API reference we read does not mention `chat_template_kwargs` or `enable_thinking`.
- On Token Factory it worked for the Nano and for the Super-120B: 329 completion tokens and 5.7 s versus 4,000 tokens (the cap) and 64 s with no output when reasoning was left on, for the same generator prompt. Because Nebius does not document the pass-through, its stability is **UNCONFIRMED**.
- **Evidence:** `docs/reasoning_control_probe.json`, `docs/reasoning_control_probe3_fixed_prompt.json`, `docs/reasoning_control_probe4_with_example.json`; the Super-120B run is described in `docs/NEBIUS_NOTES.md` section 8 and P4.6 Part 1.

### Hidden reasoning tokens are billed as completion tokens and inflate both cost and latency
- Generator call in rehearsal_001 (Nano, reasoning on): 3,903 completion tokens and 32.4 s for a visible reply of 2,499 characters (about 620 tokens at roughly 4 characters per token, an estimate). That is about 6 times the visible length.
- With the generator prompt that existed in the probe, the Nano used the entire 4,000-token cap and returned empty visible output (64 s).
- A short-answer smoke test (about 25 words): Nano 234 completion tokens, Ultra 514 completion tokens.
- **Evidence:** `recorded_runs/rehearsal_001/summary.json` and `llm_transcript.json`, `docs/reasoning_control_probe.json`, `docs/NEBIUS_NOTES.md` section 6.
- Correction: an earlier note in `docs/NEBIUS_NOTES.md` described the visible reply as "~450 tokens"; the measured character count above supersedes it.

### `response_format: json_schema`
- Accepted and honoured by both Nemotron models for a tiny two-field schema (output validated strictly), 2026-10-22. The larger nested schemas used by the analyst and fixer were never sent as `response_format`; prompt-based JSON plus Pydantic validation was used instead (UNCONFIRMED whether the server accepts them).
- The API reference page contradicts itself on this: the `type` enum lists `json_schema`, while the parameter description says "Only {'type': 'json_object'} or {'type': 'text' } is supported." (read 2026-10-22).
- **Evidence:** `docs/NEBIUS_NOTES.md` sections 6 and 7.

### Small things that were useful
- `GET /v1/models?verbose=true` returns `pricing`, `context_length` and a description per model. We used it to estimate every run's cost without hardcoding any price.
- Reasoning-model replies expose reasoning in a separate field (`reasoning_content` on the Ultra), so `content` stays clean JSON. The Nano used a differently named field (`reasoning`), so client code has to handle both (observed 2026-10-22; the Ultra field name was seen in a raw response that was not saved).

## NVIDIA Nemotron models, as observed

- **Nemotron-3-Ultra-550b-a55b (reasoning, analyst and fixer):** 15 calls across the pipeline-v1 records (rehearsal_001 and reliability_001), **0 transport errors**; latency 3.8 s minimum, 9.0 s median, 19.4 s maximum (analyst prompts of about 6,500 tokens, completion tokens 1,200 to 5,000 including hidden reasoning). Every analyst reply validated against the schema and the code-side grounding check on the first try in the 4 runs that reached the analyst. **Evidence:** `recorded_runs/rehearsal_001/summary.json`, `recorded_runs/reliability_001/run_*/summary.json`.
- **Nemotron-3-Nano-30B-A3B (generator):** with reasoning off, 8 calls in the v1 records took 2.8 to 5.3 s and 246 to 315 completion tokens. Output quality was sensitive to the prompt: with the policy parameters listed "for context" the model used them as scenario axes in 5 of 5 calls (0 of 5 valid); after removing them and listing valid key names, 4 of 5 were valid. The remaining failures were the model's arithmetic (regions below a 2% volume floor, more than 3 axes). In the v1 study 2 of 5 runs died on this. **Evidence:** `docs/reasoning_control_probe2.json`, `docs/reasoning_control_probe3_fixed_prompt.json`, `docs/P46_DIAGNOSIS.md`.
- **Nemotron-3-Ultra as fixer (pipeline v1, one patch per attempt):** proposals were conservative single- or few-lever changes with small steps; across 10 patches in 4 runs none combined a large grip force with a long hold and several retries. **Evidence:** `docs/P46_DIAGNOSIS.md` section 3.
- **Retry feedback:** in one generator failure (run_01_seed101) the retry returned a reply byte-identical to the first, ignoring the validation message. **Evidence:** `docs/P46_DIAGNOSIS.md` section 1.

## Cost, as measured
- One full pipeline-v1 run with real models: estimated about $0.03 (rehearsal_001: 9,962 prompt + 11,740 completion tokens). The five-run v1 study: 84,199 tokens, estimated $0.143. **Evidence:** `recorded_runs/rehearsal_001/summary.json`, `recorded_runs/reliability_001/summary.md`. Actual billing was not checked (UNCONFIRMED).

## Nebius AI Cloud and Serverless Jobs (documentation reading only; we ran nothing there)
- The Serverless AI overview does not state whether CPU-only jobs are supported; the quickstart and the CLI reference use GPU platforms in their examples. A Nebius-owned GitHub page recommends a CPU platform for smoke tests. CPU platforms exist for Compute VMs.
- The free trial for individuals is documented as suspended since 2026-07-13, with no replacement mentioned.
- The Token Factory billing page documents a $1 trial credit and promo credits for Token Factory and does not say whether they apply to AI Cloud.
- **Evidence and sources:** `docs/P5_FEASIBILITY.md`. We have not created any AI Cloud resource, so we have no runtime feedback on Serverless Jobs or Endpoints.

## Measured in the pipeline-v2 study (2026-10-22, 8 full runs, `recorded_runs/reliability_002`)

- **Fallback between two Nemotron models worked in practice.** The Nano's output failed validation after its retry in 3 of 8 runs; `nvidia/nemotron-3-super-120b-a12b` with the same `enable_thinking: false` request produced valid regions in all 3 (350 completion tokens at most). Estimated price of the Super: $0.30 / $0.90 per million tokens (API `pricing` field). **Evidence:** `recorded_runs/reliability_002/run_03_seed633`, `run_06_seed666`, `run_07_seed677` (`analysis_set.json` has the model trail).
- **No transport errors in the study.** 8 runs, no timeout or connection error, no 401/402/429. Per-run estimated cost $0.028 to $0.070 (median $0.032); total $0.298 for 8 runs (estimate; actual billing UNCONFIRMED). **Evidence:** `recorded_runs/reliability_002/summary.md`.
- **Time split across the 8 runs (1,110 s total):** LLM calls 26%, candidate evaluation by the simulator 41%, other simulation and gate work 32%. Latency of successful calls (min / median / max): Ultra analyst 10.7 / 12.5 / 18.5 s (7 calls), Ultra fixer 6.5 / 8.9 / 16.3 s (9 calls), Nano scenario generation with reasoning off 5.3 / 6.6 / 8.5 s (5 calls), Super-120B scenario generation with reasoning off 1.9 / 2.1 / 3.0 s (3 calls); the larger Super was faster than the Nano in this sample (small n, same day). **Evidence:** `recorded_runs/reliability_002/run_*/summary.json` (`timings_s`, `gate_timings_s`).
- **Nano formatting slip:** in run_06 the Nano replied with `region_name` instead of `name` and German region names, on both the first try and the retry; a retry does not always change the reply (v1 run_01 returned a byte-identical reply). **Evidence:** `recorded_runs/reliability_002/run_06_seed666/llm_transcript.json`.
- **Ultra analyst confusion:** in run_06 the analyst cited an evidence id that did not exist (`E49`), then on the retry listed scenario parameters (`sensor_noise_m`, `size_m`, `gripper_delay_steps`) as policy levers. The code-side validation rejected both. **Evidence:** same transcript.
- **A token cap truncated a reasoning-model reply in pipeline v1** (fixer, exactly 6,000 completion tokens, `content` was 26,467 characters of reasoning prose cut mid-sentence). The client did not record `finish_reason` then. **Evidence:** `recorded_runs/reliability_001/run_02_seed202/llm_transcript.json`, `docs/P46_FINDINGS.md`.
