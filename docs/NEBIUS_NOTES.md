# Nebius notes (P0 discovery)

Written 2026-10-21 from the official docs listed under each section. Nothing here was run against a real Nebius account: no API key and no CLI profile existed when this was written.

Labels used:
- **CONFIRMED-DOCS**: stated on an official docs page (link given). Not executed by us.
- **UNCONFIRMED**: not stated in the official docs we read, or only seen on third-party pages.
- **PENDING_KEY**: needs a real Nebius call (API key and/or CLI profile) before we can trust it. Tracked in the checklist at the bottom.

## 1. Token Factory (inference)

Sources: [Introduction](https://docs.tokenfactory.nebius.com/api-reference/introduction), [List of models](https://docs.tokenfactory.nebius.com/api-reference/examples/list-of-models), [Structured output & JSON](https://docs.tokenfactory.nebius.com/ai-models-inference/json)

| Item | Value | Status |
|---|---|---|
| Base URL | `https://api.tokenfactory.nebius.com/v1/` | CONFIRMED-DOCS |
| Auth | `Authorization: Bearer <NEBIUS_API_KEY>` | CONFIRMED-DOCS |
| API style | OpenAI-compatible (use `openai` SDK with `base_url`) | CONFIRMED-DOCS |
| List models | `GET /v1/models` (`client.models.list()`); `?verbose=true` adds name, description, context_length, architecture, quantization, pricing, per_request_limits | CONFIRMED-DOCS |
| Regional base URL variant (e.g. `api.tokenfactory.us-central1.nebius.com/v1`) | Only seen on a third-party cookbook | UNCONFIRMED. Hence `NEBIUS_BASE_URL` is an env var. |
| Structured output | `response_format` with `json_schema` or `json_object` is documented generally (example uses a Qwen model) | CONFIRMED-DOCS (general) |
| Nemotron + `json_schema` | Community reports say it works; official docs do not mention Nemotron | UNCONFIRMED, PENDING_KEY |
| Nemotron model IDs (Nano / Super / Ultra) available to our key | Not known | PENDING_KEY. Run `scripts/list_models.py`, then fill `NEBIUS_MODEL_FAST` and `NEBIUS_MODEL_REASONING`. |
| Whether a "Nemotron Ultra" exists on Token Factory under that name | Not known | UNCONFIRMED, PENDING_KEY |
| Rate limits, token pricing for our models | Not known (`?verbose=true` should include pricing) | PENDING_KEY |

Design consequence: the LLM client validates every response with Pydantic regardless of server-side schema enforcement. Server-side `json_schema` is attempted only if the config flag `NEBIUS_USE_JSON_SCHEMA=1` is set (default off until verified), otherwise the schema is put in the prompt and `json_object` mode or plain text is parsed.

## 2. Serverless Jobs (simulation fleet)

Sources: [Managing jobs](https://docs.nebius.com/serverless/jobs/manage), [Quickstart: jobs](https://docs.nebius.com/serverless/quickstart/jobs), [`nebius ai job create` reference](https://docs.nebius.com/cli/reference/ai/job/create), [nebius/skills: nebius-serverless-jobs](https://github.com/nebius/skills/blob/main/skills/nebius-serverless-jobs/SKILL.md) (Nebius-owned GitHub org, not the docs site), [serverless-ai-cookbook](https://github.com/nebius/serverless-ai-cookbook)

### Create

```bash
nebius ai job create \
  --name <job_name> \
  --image <registry/path:tag | registry/path@digest> \
  --container-command "<command>" \
  --args "<arguments>" \
  --platform <platform_ID> \
  --preset <preset> \
  --timeout <duration> \
  --subnet-id <subnet_ID>
```
CONFIRMED-DOCS. The quickstart page instead shows `nebius ai create --type job ...` with the same flags; both forms appear in the docs. We use `nebius ai job create` (it has its own reference page). PENDING_KEY: check against `nebius ai job create --help` on the installed CLI version.

Other flags from the reference (CONFIRMED-DOCS): `--env KEY=VALUE` (repeatable), `--env-secret KEY=SECRET_SELECTOR` (repeatable), `--volume`, `--inject-file LOCAL:CONTAINER` (up to 64 KiB, read-only), `--working-dir`, `--disk-size` (default 250Gi), `--shm-size`, `--restart-policy never|on-failure` (default `never`), `--parent-id`, `--async` (return immediately), `--dry-run` (validate only), `--format json|jsonpath=...`, `--registry-username/--registry-password/--registry-secret`, `--preemptible` (+ spot flags), `--on-demand`.

### Platform / preset for a CPU-only simulator

The skills page recommends `--platform cpu-d3 --preset 4vcpu-16gb` for smoke tests (Nebius-owned GitHub, not the docs site). The quickstart docs page names only GPU platforms. Discover real values with `nebius compute platform list --parent-id <project-id> --format json --all`.
Status: platform/preset names for our project/region UNCONFIRMED, PENDING_KEY (CLI profile needed). The PyBullet DIRECT sim does not need a GPU.

### Image registry

- Image ref format `registry/path:tag` or `@digest`. CONFIRMED-DOCS.
- Public registries and Nebius Container Registry in the same project need no credentials. CONFIRMED-DOCS.
- Private registries: `--registry-username/--registry-password` or `--registry-secret` (SecretStash/MysteryBox secret with keys `registry_username`, `registry_password`). CONFIRMED-DOCS.
- Pushing to Nebius Container Registry: `nebius registry configure-helper`, then `docker push cr.<region>.nebius.cloud/<registry-path>/<image>:<tag>`. Source: [Container Registry quickstart](https://docs.nebius.com/container-registry/quickstart) and [authentication](https://docs.nebius.com/container-registry/authentication), seen via search snippets only. Exact registry-creation commands UNCONFIRMED (not read in full), PENDING_KEY.

### Environment variables and secrets

`--env KEY=VALUE`; secrets via `--env-secret KEY=selector` (cannot reuse a key in both). CONFIRMED-DOCS. We pass shard config as env vars or `--inject-file` (small JSON, 64 KiB cap); larger shards must go through a volume.

### Timeouts

`--timeout`: min **1h**, max 168h, default 24h. CONFIRMED-DOCS. Consequence: we cannot ask for a short per-job timeout; the runner must enforce its own wall-clock deadline and call `nebius ai job cancel` on expiry, otherwise a hung job bills for up to the full timeout. The skills page also warns that a job whose image never pulls sits in `STARTING` until the timeout; treat >~10 minutes in STARTING as a failed pull.

### Status polling

- `nebius ai job get <id> --format json`, read `status.state` (the skills page writes `--id <job-id>`; the quickstart writes positional). CLI form UNCONFIRMED, PENDING_KEY.
- `nebius ai job get-by-name --name <name> --format jsonpath='{.metadata.id}'` to resolve ID. CONFIRMED-DOCS.
- `nebius ai job list`. CONFIRMED-DOCS.
- REST: `GET https://api.nebius.cloud/ai/v1/jobs/<job_ID>`, `status.state`. CONFIRMED-DOCS.
- States: `PROVISIONING → STARTING → RUNNING →` terminal. Only `COMPLETED` is named in the docs; the names of failure terminal states are UNCONFIRMED, PENDING_KEY. The runner must treat any terminal state that is not exactly `COMPLETED` as failure, never as success.

### Collecting outputs

Docs say results go to a mounted bucket or filesystem via `--volume`, e.g. `--volume 's3://my-bucket:/output:rw:default'` or `--volume 'storagebucket-e***:/output:rw'`. CONFIRMED-DOCS. There is no documented "download job artifact" command. Logs: `nebius ai job logs <job_ID>` (use bounded `--tail`/`--since`, avoid `--follow` in automation).

Options for returning `results.json` per shard:
1. Write to a mounted bucket, then read it with an S3-compatible client. Needs bucket + credentials. PENDING_KEY.
2. Print a delimited JSON blob to stdout and parse it from `nebius ai job logs`. Works without a bucket but is bounded by log retention/size limits (limits UNCONFIRMED). Use only for tiny shards (e.g. the P0 smoke job).

Decision is deferred to P5 and depends on what actually works.

### Cleanup

- `nebius ai job cancel <id>` stops the VM and deletes the container disk; the job stays listed; volumes are kept. CONFIRMED-DOCS.
- `nebius ai job delete <id>` removes the job and logs. CONFIRMED-DOCS.
- Volumes/buckets are not deleted with the job. CONFIRMED-DOCS.
- Permissions: `editor` role to create/cancel/delete, `viewer` to read logs. Also a VM quota of at least 1 is required. CONFIRMED-DOCS.

## 3. Serverless Endpoints (hosting the dashboard)

Source: [Managing endpoints](https://docs.nebius.com/serverless/endpoints/manage)

```bash
nebius ai endpoint create \
  --name <name> --image <image> \
  --container-port 8000 \
  --env KEY=VALUE --env-secret KEY=selector \
  --auth token --token <token> \
  --platform <platform> --preset <preset> \
  --subnet-id <subnet> --disk-size <size> \
  --public
```
CONFIRMED-DOCS. Notes:
- Each HTTP `--container-port` is exposed via a managed HTTPS URL; get it with `nebius ai endpoint get <id> --format json | jq -r '.status.public_endpoints[] | select(startswith("https://"))' | head -1`.
- `--auth token` protects it with `Authorization: Bearer <token>`. Omit `--auth` for no auth. A public demo for judges needs no auth; **UNCONFIRMED** whether the managed URL can be public without any token and what a browser visit looks like. PENDING_KEY.
- Creation takes about five minutes. `nebius ai endpoint list`, `nebius ai endpoint delete --id <id>`.
- Endpoint platforms in the docs example are GPU (`gpu-h100-sxm`). Whether a CPU preset is allowed for endpoints is UNCONFIRMED, PENDING_KEY. If not, hosting the dashboard on Nebius may cost GPU money for a CPU workload; fall back to another host and say so in the README.

## 4. PENDING_KEY checklist

Everything below needs a real Nebius key and/or CLI profile. Nothing in the code base treats these as verified.

| # | Item | Needs |
|---|---|---|
| K1 | Run `scripts/list_models.py`; choose `NEBIUS_MODEL_FAST` and `NEBIUS_MODEL_REASONING`; confirm Nemotron tiers exist | API key |
| K2 | `scripts/smoke_llm.py` (not written yet) with one real call per model | API key |
| K3 | Confirm Nemotron honours `response_format: json_schema` (decides `NEBIUS_USE_JSON_SCHEMA`) | API key |
| K4 | Real latency, token counts and cost per call; Token Factory rate limits | API key |
| K5 | Install and configure Nebius CLI; confirm project ID, region, subnet | Nebius account |
| K6 | `nebius ai job create --help` and `--dry-run` to confirm flag spelling | CLI profile |
| K7 | Create a Container Registry, push the sim image, confirm job can pull it | CLI profile, Docker running |
| K8 | Tiny test job (CPU platform) that prints a JSON line; measure startup time; check terminal state names | CLI profile |
| K9 | Decide how to return `results.json` (bucket vs logs) | CLI profile |
| K10 | Real per-job cost and wall-clock for 10 shards | CLI profile |
| K11 | Endpoint CPU preset availability and public-access behaviour | CLI profile |
| K12 | Real scenario-region proposal from the fast model (`ScenarioGenerator` has only run against a mocked client and a labelled fixture; outputs say `source: "fixture"` until then) | API key + `NEBIUS_MODEL_FAST` |
| K13 | Build state: `docker/Dockerfile.sim` (multi-stage, 1.03 GB, Python 3.11 slim + PyBullet) builds and runs the tests, API and a 200-scenario baseline locally. It has NOT been pushed to Nebius Container Registry or run as a Serverless Job; image pull and job startup behaviour are unmeasured | CLI profile, registry |
| K14 | `LocalRunner` writes one `results.json` per shard to a local directory. How `NebiusJobRunner` will get the same file back (bucket vs logs, see section 2) is undecided | CLI profile |

## 5. Local measurements so far (LocalRunner, not Nebius)

200 dev scenarios, default policy, 10 shards, 12 CPUs on the development machine: 6.1 s wall-clock, all shards completed. These say nothing about Nebius timing or cost.

## 6. CONFIRMED-BY-RUN (2026-10-22, Token Factory only; Serverless Jobs/Endpoints still untouched)

Run with `scripts/list_models.py --filter nemotron --verbose` and `scripts/smoke_llm.py --schema-test`, key in `.env` (not shown anywhere).

**Models visible to our key (Nemotron):** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/Nemotron-3_5-Lightning`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3.5-Super-VL`, `nvidia/Nemotron-3-Ultra-550b-a55b`.

| Model | Context | Price per 1M tokens (from the API's own `pricing` field): prompt / completion |
|---|---|---|
| Nemotron-3-Nano-30B-A3B | 262,144 | $0.06 / $0.24 |
| Nemotron-3_5-Lightning | 1,048,576 | $0.06 / $0.24 |
| nemotron-3-super-120b-a12b | 262,144 | $0.30 / $0.90 |
| Nemotron-3.5-Super-VL | 1,048,576 | $0.30 / $0.90 |
| Nemotron-3-Ultra-550b-a55b | 1,048,576 | $1.00 / $3.00 (cached input $0.12) |

**Choice (changeable in `.env`):**
- `NEBIUS_MODEL_FAST = nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`: the smallest text model that is explicitly a Nemotron "Nano", cheapest tier, used for volume (scenario regions). "Lightning" is the same price but its size and nature are not stated in the listing, so I did not pick it. The "Super-VL" is a vision-language model and is not needed.
- `NEBIUS_MODEL_REASONING = nvidia/Nemotron-3-Ultra-550b-a55b`: an Ultra exists and is the largest listed (550B total / 55B active, per its id). Used for failure analysis and fix proposals.

**Smoke results (real calls):**

| Call | Latency | Prompt tokens | Completion tokens |
|---|---|---|---|
| Nano, short text | 4.48 s | 49 | 234 |
| Ultra, short text | 2.03 s | 49 | 514 |
| Nano, json_schema probe | 1.97 s | not recorded | not recorded |
| Ultra, json_schema probe | 0.95 s | not recorded | not recorded |

Completion tokens are far larger than the visible answer (about 25 words): both models appear to spend hidden reasoning tokens that are billed as completion tokens. Cost estimates must budget for this. Whether reasoning can be turned down through a request parameter is UNCONFIRMED (not tried).

**K-item status:**
- K1 (list models, choose IDs): CONFIRMED-BY-RUN.
- K2 (`response_format` json_schema): CONFIRMED-BY-RUN **for a tiny schema** on both models (the API accepted it and the output validated strictly). Not yet tested with the larger nested schemas used by the analyst/fixer; the Pydantic validation and one-retry loop stay in place regardless. `NEBIUS_USE_JSON_SCHEMA` stays 0 unless set explicitly.
- K3 (smoke call per model): CONFIRMED-BY-RUN.
- K4 (latency, tokens, cost): partly confirmed (numbers above; pricing from the API). Rate limits UNCONFIRMED.
- K5 to K11 (Nebius CLI, Container Registry, Serverless Jobs, Endpoints): still UNCONFIRMED, untouched.
- K12 (real scenario-region proposal): pending, done in the rehearsal.

## 7. CONFIRMED-BY-RUN (2026-10-22, rehearsal_001: real pipeline, LocalRunner)

- **K12 (real scenario-region proposal from the fast model):** CONFIRMED-BY-RUN. One call, validated by Pydantic on the first try, `source: "llm"`.
- **Prompt-based JSON works for our three schemas:** 4 real calls (scenario regions, analyst, two fixer calls), all validated without a retry. `NEBIUS_USE_JSON_SCHEMA` stayed 0. The larger schemas were therefore never sent to the API as `response_format`; whether the server accepts them is still UNCONFIRMED. n=4, so this says nothing about long-run reliability.
- **Latency and tokens (real, from the run):** Nano scenario regions 32.5 s (989 prompt / 3,903 completion tokens); Ultra analyst 13.0 s (6,491 / 4,660); Ultra fixer 4.4 s (1,176 / 1,261) and 9.0 s (1,306 / 1,916). Completion tokens include hidden reasoning (the Nano's visible reply of 2,499 characters, about 620 tokens at roughly 4 characters per token (an estimate), cost 3,903 completion tokens).
- **Cost (ESTIMATE):** about $0.033 for the whole run: 9,962 prompt + 11,740 completion tokens x the per-token prices the API reports in `GET /models?verbose=true` ($0.06/$0.24 per 1M for Nano, $1/$3 per 1M for Ultra). Actual billing and the remaining balance were not checked: UNCONFIRMED.
- **Still untouched and UNCONFIRMED:** K5 to K11 and K13/K14 (Nebius CLI, Container Registry, Serverless Jobs, Endpoints). Everything in the rehearsal ran on the local fallback runner.

## 8. Reasoning-token control on the fast model (2026-10-22, Part 3 of P4.5)

**Problem:** in rehearsal_001 the Nano spent 3,903 completion tokens on a visible reply of 2,499 characters (about 620 tokens, an estimate) (hidden reasoning is billed as completion tokens).

**What the docs say.** The [Nebius chat-completion API reference](https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion) lists `reasoning_effort` (none, minimal, low, medium, high, xhigh, max; effect per model not defined) and says `max_completion_tokens` includes reasoning tokens. It does not mention `chat_template_kwargs` or `enable_thinking`. NVIDIA's [Nemotron-3-Nano model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16) documents `enable_thinking=False` as a chat-template switch (reasoning is on by default); the model card page itself could not be fetched here (timeout), the claim comes from search results quoting it and from NVIDIA's [RAG blueprint docs](https://docs.nvidia.com/rag/latest/enable-nemotron-thinking.html).

**What was measured (Nano, real calls; raw files in `docs/reasoning_control_probe*.json`).** The first two probe attempts failed entirely with timeouts and connection errors (`..._attempt1_infra_failure.json`, `..._attempt2_infra_failure.json`): see the outage note below.

| Variant (generator prompt, `max_tokens=4000`) | Completion tokens | Latency | Visible output |
|---|---:|---:|---|
| no control (earlier prompt version) | 4,000 (the cap) | 64 s | **empty**: all tokens spent on hidden reasoning |
| top-level `reasoning_effort="none"` | 523 | 9 s | **empty**: the whole reply sat in a `reasoning` field, `content` was empty. The parameter is accepted but unusable on this model |
| `extra_body={"chat_template_kwargs": {"enable_thinking": false}}` | 329 | 5.7 s | valid JSON text (that sample failed schema validation, see below) |

`enable_thinking: false` works on Token Factory for the Nano (CONFIRMED-BY-RUN). Pass-through is not documented by Nebius, so it could change without notice (UNCONFIRMED stability).

**Output quality with thinking off (5 real calls each, schema validation plus one retry that feeds the error back):**
- First prompt (policy parameters listed "for context"): 0 of 5 valid even after the retry; the model used `lift_height`, `grip_force` and `approach_speed` as scenario axes, made regions below the 2% volume floor, or wrote lo > hi.
- Prompt fixed (policy parameters removed, valid key names listed, rule that each range should span at least 30% of its axis): **4 of 5 valid** (1 on the first try, 3 after the retry); the failure was a 4-axis region plus a region under the volume floor. Tokens 306 to 425 per call, 4.7 to 10.6 s.
- Same prompt plus a generic format example: 3 of 5 valid (2 first try, 1 after retry). The example was dropped: n=5 cannot tell these apart and a simpler prompt carries less risk of the model copying the example.
- So with thinking off the generator is fast and cheap (about 350 tokens, 5 to 11 s) but fails validation after the single retry roughly 1 time in 5 on these samples (n=5, wide uncertainty). The pipeline fails loudly in that case; the reliability study reports it.

**Chosen controls (`backend/app/llm/controls.py`, frozen with the pipeline):** generator: `enable_thinking=false`, `max_tokens=1500`. Analyst and fixer (Ultra): reasoning stays on; `max_tokens` 10,000 and 6,000 only to stop a runaway (measured usage was 4,660 and 1,261 to 1,916).

**Before and after for the generator:** about 3,900 to 4,000+ completion tokens and 32 to 64+ s (and an empty reply in one sample) -> about 300 to 550 tokens and 5 to 15 s.

**Availability incident, 2026-10-22 (~17:00 to 17:59 local):** chat completions on the **Nano** hung with no first byte (HTTP 000 after 40 s) while `GET /models` and the **Ultra** (about 1 s), Lightning (1.1 s) and Super-120B (1.1 s) answered normally with the same key. It recovered at 17:59 (first byte 22 s for a trivial call). Two probe attempts failed during this window; both failed files are kept. The cause is on the service side (UNCONFIRMED which). The LLM client's per-call timeout is 120 s with one retry, so an outage costs up to four minutes per call before failing.

