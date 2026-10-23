"""The parameter spec the UI builds its controls from: bounds and defaults are read from the frozen config, never copied."""
from __future__ import annotations

from ..core.bounds import INT_POLICY_PARAMS, POLICY_BOUNDS, SCENARIO_BOUNDS
from ..core.schemas import PATCHABLE_PARAMS

PG_SEED_MIN, PG_SEED_MAX = 100_000, 800_000  # playground seeds: [min, max); disjoint from dev (< 100000), rehearsal and held-out blocks
DEFAULT_SEED = 200_001

SCENARIO_INFO: dict[str, dict] = {
    "mass_kg": {"label": "Cube mass", "unit": "kg", "help": "Heavier cubes are harder to grip and lift."},
    "friction": {"label": "Cube friction", "unit": "", "help": "Friction coefficient of the cube; low values are slippery."},
    "size_m": {"label": "Cube size", "unit": "m", "help": "Edge length of the cube."},
    "pos_offset_x": {"label": "Position offset x", "unit": "m", "help": "Where the cube really sits, away from where the policy expects it (forward)."},
    "pos_offset_y": {"label": "Position offset y", "unit": "m", "help": "Where the cube really sits, away from where the policy expects it (sideways)."},
    "sensor_noise_m": {"label": "Sensor noise", "unit": "m", "help": "Random error in the sensed cube position (seeded, so repeatable)."},
    "gripper_delay_steps": {"label": "Gripper delay", "unit": "steps", "help": "Delay between a gripper command and the fingers acting on it."},
}
POLICY_INFO: dict[str, dict] = {
    "grip_force": {"label": "Grip force", "unit": "N", "help": "Force limit of the finger motors while holding the cube."},
    "approach_speed": {"label": "Approach speed", "unit": "m/s", "help": "Speed of the gripper moving to the cube."},
    "lift_height": {"label": "Lift height", "unit": "m", "help": "How high the cube is lifted before it is carried over the wall."},
    "lift_speed": {"label": "Lift speed", "unit": "m/s", "help": "Speed of the lift; slower lifts shake the cube less."},
    "grasp_hold_steps": {"label": "Grasp hold", "unit": "steps", "help": "Controller steps to keep squeezing before lifting."},
    "place_slow_factor": {"label": "Place slow factor", "unit": "x", "help": "Speed multiplier near the target zone."},
    "retry_count": {"label": "Retries", "unit": "", "help": "How many times the policy may re-grasp after a missed grasp."},
}
INERT_NOTE = "Measured to have no effect on the pass rate in one-at-a-time sweeps (docs/SIM_FIDELITY.md); the fixer may not change it."

# Starting points for the presets (inputs, not results). Every value is inside the frozen bounds; "policy": None leaves the policy as it is.
PRESETS = [
    {"id": "benign", "label": "Benign", "scenario": {"mass_kg": 0.2, "friction": 0.8, "size_m": 0.05, "pos_offset_x": 0.0, "pos_offset_y": 0.0, "sensor_noise_m": 0.0, "gripper_delay_steps": 0}, "policy": None},
    {"id": "heavy_slippery", "label": "Heavy and slippery", "scenario": {"mass_kg": 0.8, "friction": 0.2, "size_m": 0.05, "pos_offset_x": 0.0, "pos_offset_y": 0.0, "sensor_noise_m": 0.005, "gripper_delay_steps": 2}, "policy": None},
    {"id": "high_noise", "label": "High noise", "scenario": {"mass_kg": 0.2, "friction": 0.8, "size_m": 0.05, "pos_offset_x": 0.0, "pos_offset_y": 0.0, "sensor_noise_m": 0.025, "gripper_delay_steps": 0}, "policy": None},
    {"id": "small_delay", "label": "Small cube with delay", "scenario": {"mass_kg": 0.2, "friction": 0.8, "size_m": 0.03, "pos_offset_x": 0.0, "pos_offset_y": 0.0, "sensor_noise_m": 0.0, "gripper_delay_steps": 15}, "policy": None},
    {"id": "default_policy", "label": "Default policy", "scenario": None, "policy": {k: v[2] for k, v in POLICY_BOUNDS.items()}},
]


def default_policy_dict() -> dict:
    return {k: (int(v[2]) if k in INT_POLICY_PARAMS else float(v[2])) for k, v in POLICY_BOUNDS.items()}


def build_spec(max_sweep_n: int) -> dict:
    scenario = [{"name": k, "min": lo, "max": hi, "integer": k == "gripper_delay_steps", "default": 0 if k == "gripper_delay_steps" else None, **SCENARIO_INFO[k]}
                for k, (lo, hi) in SCENARIO_BOUNDS.items()]
    policy = []
    for k, (lo, hi, d) in POLICY_BOUNDS.items():
        tunable = k in PATCHABLE_PARAMS
        policy.append({"name": k, "min": lo, "max": hi, "default": d, "integer": k in INT_POLICY_PARAMS, "tunable": tunable,
                       "note": None if tunable else INERT_NOTE, **POLICY_INFO[k]})
    return {
        "scenario": scenario, "policy": policy, "presets": PRESETS, "max_sweep_n": max_sweep_n, "seed": {"min": PG_SEED_MIN, "max": PG_SEED_MAX - 1, "default": DEFAULT_SEED},
        "task": "One task only: a gripper picks up a cube, carries it over a low wall and places it in a green target zone.",
        "batch": {"max_rows": 200, "max_kb": 100, "columns": list(SCENARIO_BOUNDS), "template_url": "/api/sim/batch/template"},
        "label": "Exploration, not a gate verdict. Uses the frozen simulator and parameter ranges. Not part of the official evaluation.",
        "limits": "Other robots would need a new simulator and a recalibrated gate; that is future work.",
    }
