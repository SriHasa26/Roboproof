#!/bin/sh
# Run things inside the RoboProof sim image with the repo mounted at /app (so edits are live).
#   scripts/dock.sh build              build the image (from repo root)
#   scripts/dock.sh test [pytest args] run the whole test suite
#   scripts/dock.sh api                run the FastAPI backend on http://localhost:8000
#   scripts/dock.sh baseline [args]    run scripts/run_baseline.py (200 scenarios by default)
#   scripts/dock.sh sweep [args]       run scripts/baseline_sweep.py (dev baseline table)
#   scripts/dock.sh <any command...>   e.g. scripts/dock.sh python scripts/ceiling_search.py
# Secrets: if ./.env exists it is passed as environment variables at run time (never baked into the image).
IMAGE=${ROBOPROOF_IMAGE:-roboproof-sim:dev}
ROOT=$(pwd -W 2>/dev/null || pwd)
ENVFILE=""
[ -f .env ] && ENVFILE="--env-file .env"
# the image build id is recorded in every run's artifacts (official runs refuse to start without it)
IMAGE_ID=$(docker image inspect -f '{{.Id}}' "$IMAGE" 2>/dev/null)
run() {
  MSYS_NO_PATHCONV=1 docker run --rm $ENVFILE -e ROBOPROOF_IMAGE_ID="$IMAGE_ID" -v "$ROOT:/app" -w /app "$@"
}
cmd=$1
case "$cmd" in
  build) shift; exec docker build -f docker/Dockerfile.sim -t "$IMAGE" "$@" . ;;
  test) shift; run "$IMAGE" sh -c 'cd backend && python -m pytest -q -p no:cacheprovider "$@"' sh "$@" ;;
  api) shift; run -p 8000:8000 "$IMAGE" uvicorn app.api.main:app --host 0.0.0.0 --port 8000 "$@" ;;
  baseline) shift; run "$IMAGE" python scripts/run_baseline.py "$@" ;;
  sweep) shift; run "$IMAGE" python scripts/baseline_sweep.py "$@" ;;
  *) run "$IMAGE" "$@" ;;
esac
