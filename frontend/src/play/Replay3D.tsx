import { useEffect, useMemo, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'

export type Frame = { t: number; phase: string; palm: number[]; cube: number[]; cube_q: number[]; gap: number; q: number[] }
export type Traj = { trajectory: { dt: number; frames: Frame[] }; world: { target_xy: number[]; zone_radius: number; wall_x: number; wall_half: number[]; palm_half: number[]; finger_half: number[]; finger_z: number; finger_y0: number; size_m: number } }

const S = 8 // metres to scene units
// simulator frame (x forward, y sideways, z up) to three.js (x, y up, z toward the viewer): a proper rotation, so quaternions map the same way
const v = (p: number[]): [number, number, number] => [p[0] * S, p[2] * S, -p[1] * S]

function sample(frames: Frame[], t: number): { a: Frame; b: Frame; k: number } {
  let lo = 0, hi = frames.length - 1
  while (lo < hi - 1) { const mid = (lo + hi) >> 1; if (frames[mid].t <= t) lo = mid; else hi = mid }
  const a = frames[lo], b = frames[Math.min(lo + 1, frames.length - 1)]
  const k = b.t > a.t ? Math.min(1, Math.max(0, (t - a.t) / (b.t - a.t))) : 0
  return { a, b, k }
}
const lerp3 = (a: number[], b: number[], k: number) => a.map((x, i) => x + (b[i] - x) * k)

function Scene({ d, t }: { d: Traj; t: number }) {
  const w = d.world
  const { a, b, k } = useMemo(() => sample(d.trajectory.frames, t), [d, t])
  const palm = lerp3(a.palm, b.palm, k), cube = lerp3(a.cube, b.cube, k)
  const q0 = new THREE.Quaternion(a.cube_q[0], a.cube_q[2], -a.cube_q[1], a.cube_q[3]), q1 = new THREE.Quaternion(b.cube_q[0], b.cube_q[2], -b.cube_q[1], b.cube_q[3])
  const quat = q0.clone().slerp(q1, k)
  const qq = lerp3(a.q, b.q, k)
  const f0 = [palm[0], palm[1] + (w.finger_y0 - qq[0]), palm[2] + w.finger_z], f1 = [palm[0], palm[1] - (w.finger_y0 - qq[1]), palm[2] + w.finger_z]
  const box = (h: number[]) => [h[0] * 2 * S, h[2] * 2 * S, h[1] * 2 * S] as [number, number, number] // half extents (sim x, y, z) -> scene box size
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0.15 * S, 0, 0]}><planeGeometry args={[0.7 * S, 0.5 * S]} /><meshStandardMaterial color="#0c1210" roughness={0.9} /></mesh>
      <gridHelper args={[0.7 * S, 14, '#1f2d27', '#16201c']} position={[0.15 * S, 0.003, 0]} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[w.target_xy[0] * S, 0.01, -w.target_xy[1] * S]}><circleGeometry args={[w.zone_radius * S, 40]} /><meshBasicMaterial color="#5be39a" transparent opacity={0.75} /></mesh>
      <mesh position={[w.wall_x * S, w.wall_half[2] * S, 0]}><boxGeometry args={box(w.wall_half)} /><meshStandardMaterial color="#8a8f99" roughness={0.6} /></mesh>
      <mesh position={v(palm)}><boxGeometry args={box(w.palm_half)} /><meshStandardMaterial color="#2a303b" metalness={0.5} roughness={0.4} /></mesh>
      <mesh position={v(f0)}><boxGeometry args={box(w.finger_half)} /><meshStandardMaterial color="#5c8cf0" metalness={0.4} roughness={0.4} /></mesh>
      <mesh position={v(f1)}><boxGeometry args={box(w.finger_half)} /><meshStandardMaterial color="#5c8cf0" metalness={0.4} roughness={0.4} /></mesh>
      <mesh position={v(cube)} quaternion={quat}><boxGeometry args={[w.size_m * S, w.size_m * S, w.size_m * S]} /><meshStandardMaterial color="#ff6a47" roughness={0.5} /></mesh>
    </group>
  )
}

/** Playback of a real simulated trajectory (frames recorded from PyBullet). Nothing here is animated by hand. */
export default function TrajectoryPlayer({ data, reduce }: { data: Traj; reduce: boolean }) {
  const frames = data.trajectory.frames
  const dur = frames.length ? frames[frames.length - 1].t : 0
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(!reduce)
  const [rate, setRate] = useState(1)
  const raf = useRef(0)
  useEffect(() => { setT(0); setPlaying(!reduce) }, [data, reduce])
  useEffect(() => {
    if (!playing) return
    let last = performance.now()
    const tick = (now: number) => {
      const dt = (now - last) / 1000; last = now
      let done = false
      setT((x) => { const n = x + dt * rate; if (n >= dur) { done = true; return dur } return n })
      if (done) setPlaying(false); else raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [playing, rate, dur])
  const phase = useMemo(() => (frames.length ? sample(frames, t).a.phase : ''), [frames, t])
  if (!frames.length) return <p className="text-sm text-dim">No trajectory frames in this result.</p>
  return (
    <div>
      <div className="relative h-[340px] overflow-hidden rounded-xl border hair bg-black/30 sm:h-[400px]">
        <Canvas dpr={[1, 1.5]} camera={{ position: [0.2 * S, 0.3 * S, 0.9 * S], fov: 40 }} gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}>
          <ambientLight intensity={0.8} /><directionalLight position={[3, 6, 4]} intensity={1.5} />
          <Scene d={data} t={t} />
          <OrbitControls target={[0.15 * S, 0.06 * S, 0]} enableDamping makeDefault minDistance={2} maxDistance={14} />
        </Canvas>
        <span className="pointer-events-none absolute left-3 top-2 rounded bg-black/60 px-2 py-0.5 font-mono text-[11px] text-amber">phase: {phase}</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button className="btn btn-ghost !px-4 !py-1.5 text-sm" onClick={() => { if (t >= dur) setT(0); setPlaying((p) => !p) }} aria-label={playing ? 'Pause' : 'Play'}>{playing ? 'Pause' : t >= dur ? 'Replay' : 'Play'}</button>
        <input type="range" min={0} max={dur} step={Math.max(dur / 400, 0.001)} value={t} onChange={(e) => { setPlaying(false); setT(+e.target.value) }} className="min-w-[160px] flex-1 accent-[#f2b134]" aria-label="Playback position" />
        <span className="w-28 text-right font-mono text-[11px] text-dim tick">{t.toFixed(2)} / {dur.toFixed(2)} s</span>
        <select value={rate} onChange={(e) => setRate(+e.target.value)} className="rounded-lg border border-white/15 bg-black/40 px-2 py-1 text-xs" aria-label="Playback speed">
          {[0.25, 0.5, 1, 2].map((r) => <option key={r} value={r}>{r}x</option>)}
        </select>
      </div>
      <p className="mt-2 font-mono text-[11px] text-dim">Playback of a real simulation run: {frames.length} recorded frames from the frozen PyBullet simulator, drag to orbit.</p>
    </div>
  )
}
