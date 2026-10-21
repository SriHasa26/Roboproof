"""Deterministic headless PyBullet pick-and-place environment + parameterised controller.

Embodiment: a two-finger parallel gripper whose palm is driven by a stiff world constraint
(i.e. an idealised arm: perfect Cartesian tracking, no joint dynamics). Fingers are
force-limited prismatic motors, so grasp strength comes from real PyBullet contact friction.
See docs/SIM_FIDELITY.md for what this does and does not model.

Determinism: fresh BulletClient per scenario, fixed timestep, all randomness from
numpy.default_rng(scenario.seed).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import pybullet as pb
from pybullet_utils.bullet_client import BulletClient

from ..core.schemas import FailureReason, Policy, Result, Scenario
from ..core.seeds import check_seed

DT = 1.0 / 240.0
G = 9.81
MAX_SIM_S = 25.0

# --- frozen world constants (do not tune after seeing held-out results) ---
TARGET_XY = (0.30, 0.0)
ZONE_RADIUS = 0.045
WALL_X, WALL_HALF = 0.16, (0.01, 0.20, 0.03)  # a 6 cm low wall between pick and place
PALM_HALF = (0.025, 0.08, 0.012)
FINGER_HALF = (0.02, 0.008, 0.045)  # 9 cm long: palm clears the tallest cube (8 cm)
FINGER_Z = -(PALM_HALF[2] + FINGER_HALF[2])  # finger centre below palm centre
INNER_GAP = 0.06  # finger inner face to centre line when fully open
FINGER_Y0 = INNER_GAP + FINGER_HALF[1]
FINGER_BOTTOM = FINGER_Z - FINGER_HALF[2]  # relative to palm centre
HOVER_Z = 0.22
CLOSE_SPEED = 0.25
OPEN_SPEED = 0.30
OPEN_FORCE = 60.0
LIFT_RAMP_S = 0.15  # speed ramp time -> acceleration = v / LIFT_RAMP_S
SLIP_LOST = 0.03
FINGER_FRICTION = 1.0
GEAR_RATIO = -1.0


class _Stalled(Exception):
    """Palm could not follow its target downwards (fingers landed on the cube)."""


class _Abort(Exception):
    def __init__(self, reason: FailureReason):
        self.reason = reason


@dataclass
class Trace:
    dt: float = DT * 6
    frames: list[dict] = field(default_factory=list)


class World:
    def __init__(self, scn: Scenario, record_every: int = 0, render: bool = False):
        self.scn = scn
        self.bc = BulletClient(pb.DIRECT)
        self.render = render
        self.record_every = record_every
        self.trace = Trace()
        self.images: list[np.ndarray] = []
        self.steps = 0
        self.phase = "INIT"
        self.collision = False
        self.last_cmd = 0
        self._hist: deque[int] = deque([0] * (scn.gripper_delay_steps + 1), maxlen=scn.gripper_delay_steps + 1)
        self.max_cube_lift = 0.0
        self.rel0: np.ndarray | None = None
        self.max_slip = 0.0
        self.lost_phase: str | None = None
        self.holding = False
        self.collision_cause = None
        self.touched = False
        self.contact_ok = False  # fingers allowed to touch the cube
        self._build()

    # ---------- construction
    def _build(self):
        bc, s = self.bc, self.scn
        bc.setGravity(0, 0, -G)
        bc.setPhysicsEngineParameter(fixedTimeStep=DT, numSolverIterations=120, deterministicOverlappingPairs=1,
                                     numSubSteps=0, enableFileCaching=0)
        plane_col = bc.createCollisionShape(pb.GEOM_PLANE)
        self.plane = bc.createMultiBody(0, plane_col)
        bc.changeDynamics(self.plane, -1, lateralFriction=0.8)
        zone_vis = bc.createVisualShape(pb.GEOM_CYLINDER, radius=ZONE_RADIUS, length=0.002, rgbaColor=[0.1, 0.8, 0.3, 1])
        bc.createMultiBody(0, -1, zone_vis, [TARGET_XY[0], TARGET_XY[1], 0.001])
        wcol = bc.createCollisionShape(pb.GEOM_BOX, halfExtents=WALL_HALF)
        wvis = bc.createVisualShape(pb.GEOM_BOX, halfExtents=WALL_HALF, rgbaColor=[0.5, 0.5, 0.55, 1])
        self.wall = bc.createMultiBody(0, wcol, wvis, [WALL_X, 0, WALL_HALF[2]])

        h = s.size_m / 2
        self.cube0 = np.array([s.pos_offset_x, s.pos_offset_y, h])
        ccol = bc.createCollisionShape(pb.GEOM_BOX, halfExtents=[h] * 3)
        cvis = bc.createVisualShape(pb.GEOM_BOX, halfExtents=[h] * 3, rgbaColor=[0.9, 0.3, 0.2, 1])
        self.cube = bc.createMultiBody(s.mass_kg, ccol, cvis, self.cube0.tolist())
        bc.changeDynamics(self.cube, -1, lateralFriction=s.friction, spinningFriction=0.001, restitution=0.0)

        pcol = bc.createCollisionShape(pb.GEOM_BOX, halfExtents=PALM_HALF)
        fcol = bc.createCollisionShape(pb.GEOM_BOX, halfExtents=FINGER_HALF)
        pvis = bc.createVisualShape(pb.GEOM_BOX, halfExtents=PALM_HALF, rgbaColor=[0.2, 0.2, 0.25, 1])
        fvis = bc.createVisualShape(pb.GEOM_BOX, halfExtents=FINGER_HALF, rgbaColor=[0.3, 0.5, 0.9, 1])
        self.home = np.array([0.0, 0.0, HOVER_Z])
        self.grip = bc.createMultiBody(
            baseMass=2.0, baseCollisionShapeIndex=pcol, baseVisualShapeIndex=pvis, basePosition=self.home.tolist(),
            linkMasses=[0.1, 0.1], linkCollisionShapeIndices=[fcol, fcol], linkVisualShapeIndices=[fvis, fvis],
            linkPositions=[[0, FINGER_Y0, FINGER_Z], [0, -FINGER_Y0, FINGER_Z]],
            linkOrientations=[[0, 0, 0, 1]] * 2, linkInertialFramePositions=[[0, 0, 0]] * 2,
            linkInertialFrameOrientations=[[0, 0, 0, 1]] * 2, linkParentIndices=[0, 0],
            linkJointTypes=[pb.JOINT_PRISMATIC] * 2, linkJointAxis=[[0, -1, 0], [0, 1, 0]],
        )
        for j in (0, 1):
            bc.changeDynamics(self.grip, j, lateralFriction=FINGER_FRICTION, jointLowerLimit=0.0,
                              jointUpperLimit=INNER_GAP + 0.005, jointDamping=0.0, linearDamping=0.0)
            bc.setJointMotorControl2(self.grip, j, pb.VELOCITY_CONTROL, targetVelocity=0, force=0)
        bc.changeDynamics(self.grip, -1, lateralFriction=0.5)
        # Mechanical coupling so the two fingers mirror each other (a real parallel gripper has a linkage).
        gear = bc.createConstraint(self.grip, 0, self.grip, 1, pb.JOINT_GEAR, [0, 1, 0], [0, 0, 0], [0, 0, 0])
        bc.changeConstraint(gear, gearRatio=GEAR_RATIO, maxForce=5000)
        self.palm_target = self.home.copy()
        self.cid = bc.createConstraint(self.grip, -1, -1, -1, pb.JOINT_FIXED, [0, 0, 0], [0, 0, 0], self.home.tolist())
        bc.changeConstraint(self.cid, maxForce=2000)
        self.grip_force = 0.0
        self._drive_fingers("open")
        for _ in range(30):  # let everything settle at the start
            bc.stepSimulation()

    # ---------- state
    def palm(self) -> np.ndarray:
        return np.array(self.bc.getBasePositionAndOrientation(self.grip)[0])

    def cube_pos(self) -> np.ndarray:
        return np.array(self.bc.getBasePositionAndOrientation(self.cube)[0])

    def gap(self) -> float:
        """Distance between finger inner faces (from joint encoders, i.e. what the real policy may sense)."""
        q = [self.bc.getJointState(self.grip, j)[0] for j in (0, 1)]
        return 2 * INNER_GAP - q[0] - q[1]

    def fingers_still(self) -> bool:
        return all(abs(self.bc.getJointState(self.grip, j)[1]) < 2e-3 for j in (0, 1))

    @property
    def t(self) -> float:
        return self.steps * DT

    # ---------- actuation
    def _drive_fingers(self, mode: str):
        for j in (0, 1):
            if mode == "close":
                self.bc.setJointMotorControl2(self.grip, j, pb.VELOCITY_CONTROL, targetVelocity=CLOSE_SPEED, force=self.grip_force)
            else:
                self.bc.setJointMotorControl2(self.grip, j, pb.VELOCITY_CONTROL, targetVelocity=-OPEN_SPEED, force=OPEN_FORCE)

    def command_gripper(self, mode: str, grip_force: float | None = None):
        if grip_force is not None:
            self.grip_force = grip_force
        self.last_cmd = 1 if mode == "close" else 0

    # ---------- stepping
    def step(self, n: int = 1):
        for _ in range(n):
            if self.t > MAX_SIM_S:
                raise _Abort(FailureReason.TIMEOUT)
            # gripper command latency: the motor sees the command issued `gripper_delay_steps` steps ago
            self._hist.append(self.last_cmd)
            self._drive_fingers("close" if self._hist[0] else "open")
            self.bc.changeConstraint(self.cid, jointChildPivot=self.palm_target.tolist(), maxForce=2000)
            self.bc.stepSimulation()
            self.steps += 1
            self._monitor()
            if self.record_every and self.steps % self.record_every == 0:
                self._record()

    def _contacts(self, a, b):
        return self.bc.getContactPoints(a, b)

    def _monitor(self):
        cube = self.cube_pos()
        self.max_cube_lift = max(self.max_cube_lift, cube[2] - self.scn.size_m / 2)
        if self._contacts(self.cube, self.wall):
            self._hit("cube-wall")
        if self._contacts(self.grip, self.wall):
            self._hit("gripper-wall")
        if not self.contact_ok:
            if self._contacts(self.cube, self.grip):
                self.touched = True  # tactile sensing: contact before the grasp is a stall, not yet a collision
                if np.linalg.norm((cube - self.cube0)[:2]) > 0.005:
                    self._hit("cube shoved sideways by gripper before grasp")
        else:
            if any(c[4] == -1 for c in self._contacts(self.cube, self.grip)) and self.phase not in ("RELEASE", "RETREAT"):
                self._hit("cube-palm")  # cube touching the palm itself
        if self.collision:
            raise _Abort(FailureReason.COLLISION)
        if self.holding and self.rel0 is None and self.gap() > 0.01 and self.fingers_still():
            self.rel0 = cube - self.palm()  # grasp established: slip is measured from here
        if self.holding and self.rel0 is not None:
            slip = float(np.linalg.norm((cube - self.palm()) - self.rel0))
            self.max_slip = max(self.max_slip, slip)
            if slip > SLIP_LOST and self.lost_phase is None:
                self.lost_phase = self.phase

    def _hit(self, cause: str):
        if not self.collision:
            self.collision_cause = f"{cause} @phase={self.phase} t={self.t:.2f}"
        self.collision = True

    def _record(self):
        c = self.bc.getBasePositionAndOrientation(self.cube)
        pm = self.palm()
        self.trace.frames.append({
            "t": round(self.t, 4), "phase": self.phase,
            "palm": [round(float(x), 5) for x in pm],
            "cube": [round(float(x), 5) for x in c[0]], "cube_q": [round(float(x), 5) for x in c[1]],
            "gap": round(self.gap(), 5),
            "q": [round(self.bc.getJointState(self.grip, j)[0], 5) for j in (0, 1)],
        })
        if self.render and self.steps % (self.record_every * 2) == 0:
            self.images.append(self._camera())

    def _camera(self) -> np.ndarray:
        view = self.bc.computeViewMatrix([0.15, -0.75, 0.30], [0.15, 0.0, 0.06], [0, 0, 1])
        proj = self.bc.computeProjectionMatrixFOV(45, 4 / 3, 0.1, 3.0)
        _, _, rgb, _, _ = self.bc.getCameraImage(400, 300, view, proj, renderer=pb.ER_TINY_RENDERER)
        return np.reshape(rgb, (300, 400, 4))[:, :, :3].astype(np.uint8)

    # ---------- motion primitive
    def move_to(self, target, speed: float, tol: float = 5e-4):
        """Straight-line palm move with accel-limited trapezoid profile (acceleration = speed / LIFT_RAMP_S)."""
        target = np.asarray(target, dtype=float)
        acc = max(speed, 0.05) / LIFT_RAMP_S
        v = 0.0
        for _ in range(int(MAX_SIM_S / DT)):
            delta = target - self.palm_target
            dist = float(np.linalg.norm(delta))
            if dist < tol:
                self.palm_target = target.copy()
                self.step(1)
                return
            v_stop = math.sqrt(2 * acc * dist)
            v = min(speed, v + acc * DT, v_stop)
            v = max(v, 0.02)
            self.palm_target = self.palm_target + delta / dist * min(v * DT, dist)
            self.step(1)
            if self.phase == "DESCEND" and self.touched:
                self.touched = False
                raise _Stalled()
        raise _Abort(FailureReason.TIMEOUT)

    def close(self):
        try:
            self.bc.disconnect()
        except Exception:
            pass


def _classify(w: World) -> FailureReason:
    if w.max_cube_lift < 0.01:
        return FailureReason.MISSED_GRASP
    if w.lost_phase == "LIFT":
        return FailureReason.SLIPPED_ON_LIFT
    if w.lost_phase in ("TRANSIT", "LOWER"):
        return FailureReason.DROPPED_IN_TRANSIT
    return FailureReason.PLACED_OUTSIDE_ZONE


def _execute(w: World, pol: Policy) -> None:
    s = w.scn
    rng = np.random.default_rng(s.seed)
    grasp_z = -FINGER_BOTTOM + 0.003  # fixed palm height: finger tips 3 mm above the table
    attempts = 0
    while True:
        # perceive (noisy), approach from above
        perceived = w.cube0[:2] + rng.normal(0.0, s.sensor_noise_m, 2) if attempts == 0 else w.cube_pos()[:2] + rng.normal(0.0, s.sensor_noise_m, 2)
        w.phase = "APPROACH"
        w.move_to([perceived[0], perceived[1], HOVER_Z], pol.approach_speed)
        w.phase = "DESCEND"
        try:
            w.move_to([perceived[0], perceived[1], grasp_z], pol.approach_speed)
        except _Stalled:
            w.phase = "RETRY"
            if attempts >= pol.retry_count:
                raise _Abort(FailureReason.MISSED_GRASP)
            attempts += 1
            w.palm_target = w.palm().copy()
            w.move_to([w.palm_target[0], w.palm_target[1], HOVER_Z], pol.approach_speed)
            continue
        w.phase = "GRASP"
        w.contact_ok = True
        w.command_gripper("close", pol.grip_force)
        w.step(pol.grasp_hold_steps)
        w.holding = True  # rel0 is latched in World._monitor once the fingers stop
        w.phase = "LIFT"
        lift_z = grasp_z + pol.lift_height
        w.move_to([w.palm_target[0], w.palm_target[1], lift_z], pol.lift_speed)
        w.step(10)
        in_hand = w.gap() > 0.01 and w.fingers_still()
        if in_hand:
            break
        w.holding = False
        w.phase = "RETRY"
        if attempts >= pol.retry_count:
            raise _Abort(_classify(w))
        attempts += 1
        w.command_gripper("open")
        w.step(40)
        w.contact_ok = False
        w.move_to([w.palm_target[0], w.palm_target[1], HOVER_Z], pol.approach_speed)
        w.rel0, w.max_slip, w.lost_phase = None, 0.0, None

    # transit to just short of the target, then slow final approach
    w.phase = "TRANSIT"
    tx, ty = TARGET_XY
    start = w.palm_target[:2]
    vec = np.array([tx, ty]) - start
    dist = float(np.linalg.norm(vec))
    pre = start + vec / dist * max(dist - 0.06, 0.0)
    w.move_to([pre[0], pre[1], lift_z], pol.approach_speed)
    w.move_to([tx, ty, lift_z], pol.approach_speed * pol.place_slow_factor)
    w.phase = "LOWER"
    w.move_to([tx, ty, grasp_z + 0.004], pol.approach_speed * pol.place_slow_factor)
    w.phase = "RELEASE"
    w.holding = False
    w.command_gripper("open")
    w.step(50 + s.gripper_delay_steps)
    w.completion = w.t
    w.phase = "RETREAT"
    w.move_to([tx, ty, lift_z], 0.3)
    w.phase = "SETTLE"
    w.step(90)


def run_scenario(policy: Policy, scenario: Scenario, record: bool = False, render: bool = False,
                 record_every: int = 6, held_out: bool = False) -> tuple[Result, Trace | None, list[np.ndarray]]:
    """Run one scenario. Same (policy, scenario) always gives the same Result.

    Seeds in the held-out range raise HeldOutSeedError unless held_out=True (gate only, see core/seeds.py).
    """
    check_seed(scenario.seed, held_out)
    w = World(scenario, record_every=record_every if (record or render) else 0, render=render)
    w.completion = None
    reason: FailureReason | None = None
    try:
        try:
            _execute(w, policy)
        except _Abort as a:
            reason = a.reason
        cube = w.cube_pos()
        err = float(np.hypot(cube[0] - TARGET_XY[0], cube[1] - TARGET_XY[1]))
        if reason is None:
            vel = np.linalg.norm(w.bc.getBaseVelocity(w.cube)[0])
            upright = abs(cube[2] - scenario.size_m / 2) < 0.01 and vel < 0.02
            if not (err <= ZONE_RADIUS and upright):
                reason = _classify(w)
        t_done = w.completion if w.completion is not None else w.t
        res = Result(
            scenario_id=scenario.id, seed=scenario.seed, success=reason is None, collision=w.collision,
            completion_time_s=round(t_done, 4), final_place_error_m=round(err, 5), max_slip_m=round(w.max_slip, 5),
            failure_reason=reason,
            trajectory_summary={"max_cube_lift_m": round(w.max_cube_lift, 4), "steps": float(w.steps)},
        )
        return res, (w.trace if record or render else None), w.images
    finally:
        w.close()
