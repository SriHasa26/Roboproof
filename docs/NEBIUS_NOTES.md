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

