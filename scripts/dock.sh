#!/bin/sh
# Run a command inside the simulator image with the repo mounted at /app (dev helper; PyBullet needs Linux here).
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W 2>/dev/null || pwd):/app" -w /app roboproof-sim:dev "$@"
