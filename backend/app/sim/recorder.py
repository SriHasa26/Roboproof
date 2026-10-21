"""Replay recorder: trajectory JSON (for canvas playback) and GIF (for README / side-by-side clips)."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from ..core.schemas import Policy, Result, Scenario
from .pickplace import DT, TARGET_XY, ZONE_RADIUS, run_scenario


def record_scenario(policy: Policy, scenario: Scenario, out_dir: str | Path, gif: bool = True,
                    label: str = "") -> tuple[Result, Path, Path | None]:
    """Run `scenario` and write <id>[_label].traj.json (+ .gif). The Result is identical to a non-recording run."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result, trace, images = run_scenario(policy, scenario, record=True, render=gif)
    stem = f"{scenario.id}{'_' + label if label else ''}"
    traj_path = out / f"{stem}.traj.json"
    traj_path.write_text(json.dumps({
        "scenario": scenario.model_dump(), "policy": policy.model_dump(), "result": result.model_dump(mode="json"),
        "dt": trace.dt, "sim_dt": DT, "target_xy": TARGET_XY, "zone_radius": ZONE_RADIUS, "frames": trace.frames,
        "note": "simulation (PyBullet DIRECT); see docs/SIM_FIDELITY.md",
    }))
    gif_path = None
    if gif and images:
        gif_path = out / f"{stem}.gif"
        frames = [Image.fromarray(im).resize((320, 240)) for im in images]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=int(trace.dt * 2 * 1000), loop=0)
    return result, traj_path, gif_path
