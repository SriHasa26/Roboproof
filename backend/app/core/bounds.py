"""Frozen parameter ranges. Chosen once; do not tune after seeing held-out results."""
from __future__ import annotations

# (min, max) for scenario axes, from PROJECT_BRIEF.md section 3.1
SCENARIO_BOUNDS: dict[str, tuple[float, float]] = {
    "mass_kg": (0.05, 1.0),
    "friction": (0.1, 1.2),
    "size_m": (0.03, 0.08),
    "pos_offset_x": (-0.08, 0.08),
    "pos_offset_y": (-0.08, 0.08),
    "sensor_noise_m": (0.0, 0.03),
    "gripper_delay_steps": (0, 20),
}

# (min, max, default) for tunable policy parameters.
# FROZEN in P2: defaults chosen using DEV seeds only (sweep seeds 7 and 11, seed base 1000); see docs/SIM_FIDELITY.md.
# Do not change after seeing held-out results.
POLICY_BOUNDS: dict[str, tuple[float, float, float]] = {
    "grip_force": (5.0, 80.0, 15.0),
    "approach_speed": (0.05, 0.6, 0.3),
    "lift_height": (0.05, 0.30, 0.15),
    "lift_speed": (0.05, 0.6, 0.3),
    "grasp_hold_steps": (0, 120, 10),
    "place_slow_factor": (0.1, 1.0, 1.0),
    "retry_count": (0, 3, 0),
}
INT_POLICY_PARAMS = {"grasp_hold_steps", "retry_count"}
