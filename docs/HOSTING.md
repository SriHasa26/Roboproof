# Hosting RoboProof on a small free container host

One container serves the built site and the API on a single port. Nothing here is deployed by this repository; it is the recipe and the measured limits.

## What the host does to you (for example Render free)

Facts about the host, taken from its own terms at the time of writing (check their current docs): the service **spins down after about 15 minutes without traffic** and wakes on the next request in **roughly a minute**; **local disk is lost** when it spins down; CPU and RAM are small. RoboProof is built around those three facts.

| Fact | What RoboProof does |
|---|---|
| Spins down when idle, wakes in about a minute | The site shows **"Backend waking up (about 1 minute)"** and retries the health check every 3 s for up to **90 s**, then falls back to offline mode with recorded data. It shows "Backend online" only after `/api/health` has answered. A host that answers with a 404 or HTML (a static host with no API) is treated as offline at once, without waiting. |
| Local disk is lost | Runtime data goes to `DATA_DIR` (default `/tmp/roboproof`): kept live-run folders, the daily live-run and spend counters, the SQLite file. **They reset whenever the host restarts or spins down**, so the daily caps are per instance lifetime, not a durable quota. Only the newest 20 runs are kept (`LIVE_KEEP_RUNS`). Recorded runs and replays are baked into the image and are not affected. |
| Small CPU and RAM | Worker counts come from the container's real CPU limit (cgroup quota, not the host's core count: a 0.5 CPU container starts 1 simulator worker). In host mode a sweep is at most 50 scenarios and a batch at most 50 rows. See "Measured" below. |

## The image

`docker/Dockerfile.host` is multi-stage: Node builds the frontend (with `VITE_API_BASE` unset, so the site calls the relative `/api` on its own origin), a Python stage compiles PyBullet, and a slim runtime stage copies in the backend, the built site and the five recorded official runs. It runs as a **non-root user** (`app`, uid 10001) and listens on `$PORT` (Render sets 10000; the image defaults to 7860).

```bash
docker build -f docker/Dockerfile.host -t roboproof-host:dev .
docker run --rm -p 7860:7860 -e PORT=7860 roboproof-host:dev        # open http://localhost:7860
docker run --rm -p 7860:7860 -e PORT=7860 --memory=512m --cpus=0.5 roboproof-host:dev   # the smallest host profile
```

`render.yaml` is a Blueprint for a free Docker web service (`healthCheckPath: /api/health`, no secret values; the secrets are `sync: false` and entered in the dashboard).

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 7860 (Render: 10000) | Port the single server listens on (the host sets it). |
| `ROBOPROOF_HOST_MODE` | `1` in the host image, else off | Small defaults for the limits below. |
| `DATA_DIR` | `/tmp/roboproof` | Runtime data directory (local disk; lost on spin-down). |
| `MAX_SWEEP_N` | 50 in host mode, else 200 | Largest sweep. Never above 200. (`PLAYGROUND_MAX_SWEEP_N` still works.) |
| `MAX_BATCH_ROWS` | 50 in host mode, else 200 | Largest CSV batch. Never above 200. |
| `RUN_TIMEOUT_S` | 600 | A full pipeline run is killed after this long (`LIVE_TIMEOUT_S` still works). |
| `PLAYGROUND_ENABLED` | 1 | Kill switch for the simulator playground. |
| `STARTUP_SELF_CHECK` | on in host mode | At start the server imports the simulator and builds the playground spec; if either fails it refuses to start with a clear message. |
| `LIVE_ENABLED` | 0 | Master switch for anything that calls a model or spends credits (full pipeline, plain-English input, analysis). |
| `LIVE_PIPELINE_ENABLED` | 1 | **0 disables only the full pipeline run.** Scenario, sweep, batch, interpret and analyze keep working. |
| `LIVE_KEEP_RUNS` | 20 | Finished run folders kept on disk. |
| `LIVE_DAILY_RUN_CAP`, `LIVE_DAILY_USD_CAP`, `LIVE_RATE_PER_IP_PER_HOUR`, `LIVE_ACCESS_CODE` | 10, 1.0, 3, none | Spend and abuse limits (reset on restart on this kind of host). |
| `LIVE_TRUST_PROXY` | 0 | Set to 1 behind a proxy (Render) so the client address comes from `X-Forwarded-For`. |
| `NEBIUS_API_KEY`, `NEBIUS_BASE_URL`, `NEBIUS_MODEL_FAST`, `NEBIUS_MODEL_REASONING`, `NEBIUS_MODEL_FALLBACK` | none | Set in the host's dashboard only. Never in the image, the repo or the browser. |

With `LIVE_PIPELINE_ENABLED=0`, `/live` shows the recorded replays and says that full pipeline runs are available when the project is run locally. `GET /api/version` reports `effective_cpus`, `workers` and `memory_limit_bytes` as the container sees them.

## Measured

`scripts/measure_hosting.py` starts a fresh container per (limit, operation) and records time, peak memory (the cgroup's own high-water mark, idle server included) and whether anything was OOM-killed. The numbers from this machine are in [HOSTING_MEASUREMENTS.md](HOSTING_MEASUREMENTS.md). They are single measurements on a development laptop, not benchmarks. At the time of writing nothing was killed in either profile and the peak stayed under about 141 MiB, so 512 MB of RAM was enough for these operations; the 0.5 CPU profile was about 5 times slower than 2 CPUs (about 20 s for a 50-scenario sweep or a 50-row batch against about 4 s). A host with less CPU than 0.5 was not measured and would be slower still.

## What this setup cannot do

- The full pipeline run was not measured in a constrained container (it spends model credits); only scenario, sweep and batch were. A run takes minutes and, on a host that sleeps and loses its disk, is a poor fit, so `LIVE_PIPELINE_ENABLED=0` is the sensible setting there. Run the pipeline locally or on a larger instance.
- Daily quotas and kept runs are not durable across restarts.
- The first visit after idle shows the waking state; nothing is faked while it waits.
