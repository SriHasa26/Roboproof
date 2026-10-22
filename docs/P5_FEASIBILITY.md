# P5 feasibility: Nebius Serverless Jobs for the simulation fleet

Research only, written 2026-10-22 from the official docs. Nothing was installed, created, pushed or run on Nebius AI Cloud, and no money was spent.
Labels: **CONFIRMED-DOCS** (stated on an official docs page, linked), **THIRD-PARTY** (not from Nebius), **UNCONFIRMED** (not stated, or only inferred). Prices change; the docs say CPU prices changed on 2026-10-01, so check the console before budgeting.

## Answers

### 1. Can a Serverless Job run on CPU only?

**Probably yes, UNCONFIRMED by the Serverless docs.**
- The [Serverless AI overview](https://docs.nebius.com/serverless/overview) does not say whether CPU-only deployments are supported (it mentions both GPU and vCPU utilization). The [jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs) and the `nebius ai job create` reference use GPU platforms in their examples (`gpu-l40s-a`, `gpu-h100-sxm`; the CLI default platform is `gpu-h100-sxm`, or `gpu-h200-sxm` outside eu-north1).
- The Nebius-owned [nebius/skills serverless-jobs page](https://github.com/nebius/skills/blob/main/skills/nebius-serverless-jobs/SKILL.md) (a GitHub repo, not the docs site) recommends `--platform cpu-d3 --preset 4vcpu-16gb` for smoke tests and says to discover options with `nebius compute platform list --parent-id <project-id> --format json --all`.
- CPU-only Compute platforms exist ([VM types](https://docs.nebius.com/compute/virtual-machines/types), CONFIRMED-DOCS): `cpu-d3` (AMD EPYC Genoa), smallest preset `2vcpu-8gb`, up to `256vcpu-1024gb`, in eu-north1, eu-west1, me-west1, us-central1, uk-south1, uk-south2, eu-south1, eu-west2, us-north1; and `cpu-e2` (Intel Ice Lake), smallest `2vcpu-8gb`, eu-north1 only. Availability also depends on the project.
- **How to settle it for free:** `nebius ai job create ... --platform cpu-d3 --preset 2vcpu-8gb --dry-run` validates the request without creating anything (flag listed in the [CLI reference](https://docs.nebius.com/cli/reference/ai/job/create)). Whether `--dry-run` also checks quota and platform availability is UNCONFIRMED.
- **If CPU turns out to be unsupported:** the cheapest GPU option is `gpu-l40s-a`, preset `1gpu-8vcpu-32gb`, eu-north1 only (CONFIRMED-DOCS), at about $1.55 per hour on demand (section 3). The simulator does not use the GPU, so this would be roughly 25 times the CPU cost for no benefit.

### 2. What does an individual account need?

CONFIRMED-DOCS unless marked:
- **A paid account.** "The free trial program in Nebius AI Cloud has been suspended as of July 13, 2026. New sign-ups aren't accepted." ([free trial](https://docs.nebius.com/signup-billing/free-trial)). The page does not say what happens to existing trial accounts, and mentions no replacement credits or grants. If you do not already have an AI Cloud account with a payment method, the docs give no way for an individual to create one for free.
- **Payment.** Individuals pay by bank card; the balance is debited in real time, the card is charged at the start of the month if the balance is negative, and a failed card charge suspends the account ([card payments](https://docs.nebius.com/signup-billing/payments/card), [Token Factory billing](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new) for the same mechanism). A "$25 minimum first payment" appears only in a THIRD-PARTY review, so treat it as UNCONFIRMED.
- **Quota and access.** At least one VM available under the Compute quota "Number of virtual machines"; the `editor` role to create, cancel and delete jobs; a CLI profile with a project ID (the CLI prompts for project, region and subnet) ([jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs), [managing jobs](https://docs.nebius.com/serverless/jobs/manage)). Installing and configuring the Nebius CLI is a prerequisite; its install steps were not read for this document.
- **Do Token Factory promo credits apply to AI Cloud?** UNCONFIRMED, probably not. The Token Factory billing page documents a $1 trial credit valid for 30 days for new Token Factory sign-ups and promo codes that give "free Nebius Token Factory credits", and says nothing about sharing a balance with Compute or Serverless AI. Ask Nebius support or look at the Billing page in the console before assuming they carry over.

### 3. Billing model and a rough cost estimate

- **Billing:** usage-based, per second, for compute and storage while a job runs; mounted buckets and filesystems are billed separately ([overview](https://docs.nebius.com/serverless/overview)). VMs have no stated minimum charge ([compute pricing](https://docs.nebius.com/compute/resources/pricing)). Whether time spent in `PROVISIONING`/`STARTING` (image pull) is billed is UNCONFIRMED.
- **Prices (USD, ex tax; from the pricing page, which lists the Genoa platform as "Non-GPU AMD Epyc Genoa", not `cpu-d3`):** CPU $0.015 per vCPU-hour and RAM $0.0045 per GiB-hour from 2026-10-01 (before: $0.012 and $0.0032). L40S GPU on demand $1.35 per GPU-hour plus $0.012 per vCPU-hour and $0.0032 per GiB-hour. Network SSD disk $0.071 per GiB per 730 hours.
- **Cost of one `2vcpu-8gb` CPU job:** 2 x $0.015 + 8 x $0.0045 = **$0.066 per hour** ($0.0000183 per second).

**Estimate for one full pipeline run** (assumptions are mine, not measured on Nebius):
- Work: from rehearsal_001 on LocalRunner, a 250-scenario run is about 100 CPU-seconds in total (8.6 s on 12 cores), so about 0.4 CPU-s per scenario. One pipeline run with two fixer attempts simulates about 250 (baseline) + 30 (G1) + 45 (G2) + 2 x 250 (patched) + 800 (G5: 400 unpatched + 400 patched) = **about 1,600 scenarios, about 650 CPU-seconds**.
- Fan-out: 10 shards per run call and about 6 run calls (baseline, G1, G2, each patched attempt, G5 x2) = **about 60 short jobs**.
- Per-job overhead (image pull of a 1 GB image plus VM start) is the big unknown, UNCONFIRMED. Scenarios: 2 minutes per job (optimistic), 10 minutes per job (pessimistic).

| Scenario | Job-hours | CPU cost (`2vcpu-8gb`, $0.066/h) | Same on `gpu-l40s-a` ($1.55/h) |
|---|---|---|---|
| 2 min per job, 60 jobs | 2.0 h | about $0.13 | about $3.1 |
| 10 min per job, 60 jobs | 10.0 h | about $0.66 | about $15.5 |

Plus the disk (20 GiB minimum for CPU; about $0.0019 per hour per job, negligible) and a tiny test job (about $0.01). **So a CPU run is on the order of $0.1 to $1; a GPU fallback would be $3 to $15 and is not worth it.** The estimate ignores retries, failed pulls (a job whose image never pulls "sits in STARTING, billing, until the timeout" per the skills page, and the minimum job timeout is 1 hour, so a pull failure can bill up to an hour unless cancelled), and the cost of reading results back.

### 4. Is a Container Registry required?

No (CONFIRMED-DOCS). "Public registries and Container Registry in the same project need no credentials"; private registries need `--registry-username/--registry-password` or `--registry-secret` ([managing jobs](https://docs.nebius.com/serverless/jobs/manage)). The quickstart's example image is a public Docker Hub image.

Minimal path for our roughly 1 GB image, in order of effort:
1. **Public registry** (Docker Hub or GitHub Container Registry, public image): `docker push`, then `--image <registry/path:tag>` with no credentials. The image holds only MIT-licensed code and docs and no secrets (the API key is passed at run time, and simulation jobs do not need it). This avoids Nebius registry setup but depends on the Nebius VM being able to pull from that registry (UNCONFIRMED until tried).
2. **Nebius Container Registry:** `nebius registry configure-helper`, then `docker push cr.<region>.nebius.cloud/<registry-path>/<image>:<tag>` ([quickstart](https://docs.nebius.com/container-registry/quickstart), read only through search snippets: the exact registry-creation commands are UNCONFIRMED). Pushing 1 GB from this machine also depends on upload bandwidth.

Getting results back is the other open question (UNCONFIRMED). Jobs mount buckets/filesystems with `--volume`; there is no documented download-artifact command. A shard's results are about 8 KB of JSON, which could go through `nebius ai job logs` (log size limits UNCONFIRMED) or a mounted bucket (needs a bucket and credentials). Shard inputs are small enough for `--inject-file` (64 KiB limit).

### 5. Recommendation: conditional GO, time-boxed, with LocalRunner as the labelled fallback

The hackathon requires Token Factory or AI Cloud plus an NVIDIA open model; **Token Factory with Nemotron already satisfies that.** Serverless Jobs are encouraged, not required, and CLAUDE.md says the local runner is acceptable if clearly labelled.

- **GO** only if you already have, or are willing to create, a paid AI Cloud account with a card, and accept a hard spending cap of about $2 for the feasibility attempt. A successful attempt is cheap (section 3) and would make the "simulations run on Nebius Serverless Jobs" claim true.
- **NO-GO** if there is no way to get a funded AI Cloud account (the free trial is suspended). In that case keep LocalRunner, label every run "local fallback, not Nebius" (already done), and say so in the README and the submission.
- **Order of attempts (stop at the first blocker):** (1) install the CLI and confirm a profile, project and subnet; (2) `nebius compute platform list` and `nebius ai job create --dry-run` with `cpu-d3` to settle CPU support for free; (3) push the image to a public registry; (4) one tiny job that prints one JSON line, recording the real state names, startup time, and whether `logs` returns it; (5) only then build `NebiusJobRunner` and compare with `scripts/compare_runs.py`.

### What you would need to do manually
1. Decide GO or NO-GO (above).
2. For GO: a Nebius AI Cloud account with a bank card, project, region (CPU `cpu-d3` is listed in eu-north1 and many others), subnet, the `editor` role, and a VM quota of at least 1.
3. Install and configure the Nebius CLI (`nebius profile create`, as described in the CLI quickstart, which I have not read).
4. Choose a registry (public Docker Hub / GHCR account, or a Nebius Container Registry).
5. Tell me the spending cap. I will not create anything on Nebius without your explicit go.

## Sources
- [Serverless AI overview](https://docs.nebius.com/serverless/overview)
- [Jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs) and [Managing jobs](https://docs.nebius.com/serverless/jobs/manage)
- [`nebius ai job create`](https://docs.nebius.com/cli/reference/ai/job/create)
- [VM types: platforms and presets](https://docs.nebius.com/compute/virtual-machines/types)
- [Compute pricing](https://docs.nebius.com/compute/resources/pricing)
- [Free trial for individual users](https://docs.nebius.com/signup-billing/free-trial) and [card payments](https://docs.nebius.com/signup-billing/payments/card)
- [Token Factory billing](https://docs.tokenfactory.nebius.com/other-capabilities/billing-new)
- [Container Registry quickstart](https://docs.nebius.com/container-registry/quickstart)
- [nebius/skills: nebius-serverless-jobs](https://github.com/nebius/skills/blob/main/skills/nebius-serverless-jobs/SKILL.md) (Nebius-owned GitHub repo)
