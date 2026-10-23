import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Canvas, ThreeEvent } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'

export type ScenData = {
  set: string; policy: string; n: number; ids: string[]; tag: (string | null)[]; ok: number[]; reason: (string | null)[]
  mass_kg: number[]; friction: number[]; size_m: number[]; sensor_noise_m: number[]; gripper_delay_steps: number[]; pos_offset_x: number[]; pos_offset_y: number[]
}
export const AXES: { key: keyof ScenData; label: string; unit: string }[] = [
  { key: 'mass_kg', label: 'mass', unit: 'kg' }, { key: 'friction', label: 'friction', unit: '' }, { key: 'sensor_noise_m', label: 'sensor noise', unit: 'm' },
  { key: 'gripper_delay_steps', label: 'gripper delay', unit: 'steps' }, { key: 'size_m', label: 'size', unit: 'm' },
]
const SPAN = 4
const GREEN = new THREE.Color('#5be39a'), RED = new THREE.Color('#ff6a47')

function Points({ d, ok, ax, showPass, showFail, onHover, onPick }: { d: ScenData; ok: number[]; ax: [number, number, number]; showPass: boolean; showFail: boolean; onHover: (i: number | null) => void; onPick?: (i: number) => void }) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const range = useMemo(() => AXES.map((a) => { const v = d[a.key] as number[]; return [Math.min(...v), Math.max(...v)] as [number, number] }), [d])
  useLayoutEffect(() => {
    const m = mesh.current
    if (!m) return
    const o = new THREE.Object3D()
    for (let i = 0; i < d.n; i++) {
      const vis = ok[i] ? showPass : showFail
      const p = [0, 1, 2].map((k) => { const [lo, hi] = range[ax[k]]; const v = (d[AXES[ax[k]].key] as number[])[i]; return ((hi > lo ? (v - lo) / (hi - lo) : 0.5) - 0.5) * SPAN })
      o.position.set(p[0], p[1], p[2])
      o.scale.setScalar(vis ? (ok[i] ? 1 : 1.35) : 0.0001)
      o.updateMatrix()
      m.setMatrixAt(i, o.matrix)
      m.setColorAt(i, ok[i] ? GREEN : RED)
    }
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
    m.computeBoundingSphere()
  }, [d, ok, ax, range, showPass, showFail])
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, d.n]}
      onPointerMove={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); const i = e.instanceId ?? null; onHover(i != null && (ok[i] ? showPass : showFail) ? i : null) }}
      onClick={(e: ThreeEvent<MouseEvent>) => { if (onPick && e.instanceId != null && (ok[e.instanceId] ? showPass : showFail)) { e.stopPropagation(); onPick(e.instanceId) } }}
      onPointerOut={() => onHover(null)}>
      <sphereGeometry args={[0.07, 14, 14]} />
      <meshStandardMaterial roughness={0.35} metalness={0.2} emissive="#101010" />
    </instancedMesh>
  )
}

function Frame({ ax }: { ax: [number, number, number] }) {
  const h = SPAN / 2
  const box = useMemo(() => new THREE.EdgesGeometry(new THREE.BoxGeometry(SPAN, SPAN, SPAN)), [])
  const lab = (pos: [number, number, number], k: number) => (
    <Html position={pos} center distanceFactor={9} zIndexRange={[5, 0]}><span className="whitespace-nowrap rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-amber">{AXES[ax[k]].label}{AXES[ax[k]].unit ? ` (${AXES[ax[k]].unit})` : ''}</span></Html>
  )
  return (
    <group>
      <lineSegments geometry={box}><lineBasicMaterial color="#2a3a33" /></lineSegments>
      {lab([0, -h - 0.25, h], 0)}{lab([h + 0.3, 0, h], 1)}{lab([-h, -h - 0.25, 0], 2)}
    </group>
  )
}

export default function FailureMap3D({ d, reduce, alt, onPick, pickHint }: { d: ScenData; reduce: boolean; alt?: { ok: number[]; reason: (string | null)[]; label: string; main: string }; onPick?: (i: number) => void; pickHint?: string }) {
  const [useAlt, setUseAlt] = useState(false)
  const ok = useAlt && alt ? alt.ok : d.ok
  const reasons = useAlt && alt ? alt.reason : d.reason
  const [ax, setAx] = useState<[number, number, number]>([0, 1, 2])
  const [showPass, setShowPass] = useState(true), [showFail, setShowFail] = useState(true)
  const [hover, setHover] = useState<number | null>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  useEffect(() => { setHover(null) }, [ax, showPass, showFail])
  const set = (k: number, v: number) => setAx((a) => { const n = [...a] as [number, number, number]; const j = n.indexOf(v); if (j >= 0 && j !== k) n[j] = n[k]; n[k] = v; return n })
  const nFail = ok.filter((x) => !x).length
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        {(['x', 'y', 'z'] as const).map((n, k) => (
          <label key={n} className="flex items-center gap-1.5 text-dim">{n.toUpperCase()}
            <select value={ax[k]} onChange={(e) => set(k, +e.target.value)} className="rounded-lg border border-white/15 bg-black/40 px-2 py-1 text-text">
              {AXES.map((a, i) => <option key={a.key} value={i}>{a.label}</option>)}
            </select></label>
        ))}
        <label className="flex items-center gap-1.5 text-dim"><input type="checkbox" className="accent-[#5be39a]" checked={showPass} onChange={(e) => setShowPass(e.target.checked)} />pass</label>
        <label className="flex items-center gap-1.5 text-dim"><input type="checkbox" className="accent-[#ff6a47]" checked={showFail} onChange={(e) => setShowFail(e.target.checked)} />fail</label>
        <div className="ml-auto flex overflow-hidden rounded-full border border-white/15 text-xs" role="group" aria-label="Policy shown">
          {alt ? (<>
            <button className={`px-3 py-1 ${!useAlt ? 'bg-white/10' : 'text-dim hover:text-text'}`} aria-pressed={!useAlt} onClick={() => setUseAlt(false)}>{alt.main}</button>
            <button className={`px-3 py-1 ${useAlt ? 'bg-white/10' : 'text-dim hover:text-text'}`} aria-pressed={useAlt} onClick={() => setUseAlt(true)}>{alt.label}</button>
          </>) : (<>
            <span className="bg-white/10 px-3 py-1">unpatched policy</span>
            <span className="cursor-not-allowed px-3 py-1 text-dim/60" title="The pipeline did not store per-scenario results for the patched policy, so there is nothing real to show here.">patched: not stored</span>
          </>)}
        </div>
      </div>
      <div ref={wrap} className="relative h-[380px] overflow-hidden rounded-xl border hair bg-black/30 sm:h-[460px]" onPointerMove={(e) => { const r = wrap.current!.getBoundingClientRect(); setPos({ x: e.clientX - r.left, y: e.clientY - r.top }) }}>
        <Canvas dpr={[1, 1.5]} camera={{ position: [5.2, 3.4, 6], fov: 42 }} gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}>
          <ambientLight intensity={0.7} /><directionalLight position={[4, 6, 5]} intensity={1.4} />
          <Frame ax={ax} />
          <Points d={d} ok={ok} ax={ax} showPass={showPass} showFail={showFail} onHover={setHover} onPick={onPick} />
          <OrbitControls enableDamping makeDefault autoRotate={!reduce} autoRotateSpeed={0.5} minDistance={4} maxDistance={16} />
        </Canvas>
        {hover != null && (
          <div className="pointer-events-none absolute z-10 max-w-[16rem] rounded-lg border border-white/15 bg-black/85 p-2.5 font-mono text-[11px] leading-relaxed" style={{ left: Math.min(pos.x + 14, (wrap.current?.clientWidth ?? 400) - 260), top: Math.max(pos.y - 8, 4) }}>
            <div className={ok[hover] ? 'text-phos' : 'text-verm'}>{d.ids[hover]}: {ok[hover] ? 'PASS' : `FAIL (${reasons[hover] ?? 'no reason code'})`}</div>
            {AXES.map((a) => <div key={a.key} className="text-dim">{a.label} {Number((d[a.key] as number[])[hover]).toPrecision(3)} {a.unit}</div>)}
          </div>
        )}
        <p className="pointer-events-none absolute bottom-2 left-3 font-mono text-[10px] text-dim">drag to orbit, scroll to zoom, hover a point{pickHint ? `, ${pickHint}` : ''}</p>
      </div>
      <p className="mt-2 font-mono text-[11px] text-dim">{d.set} ({d.n} scenarios, {nFail} fail), {useAlt && alt ? alt.label : d.policy}. Each point is one real simulated scenario.</p>
    </div>
  )
}
