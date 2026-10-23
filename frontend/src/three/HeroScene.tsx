import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import * as THREE from 'three'

/* Procedural pick-and-place loop built from primitives. Purely illustrative: no physics, no simulation data. */
const L1 = 1.5, L2 = 1.5, SHOULDER_Y = 0.6, PERIOD = 9
const PICK = new THREE.Vector3(-1.3, 0.15, 0.4), PAD = new THREE.Vector3(1.3, 0.02, 0.4)
const WRIST_DOWN = 0.3 // wrist height above the cube centre while gripping

const ease = (t: number) => t * t * (3 - 2 * t)
const lerpV = (a: THREE.Vector3, b: THREE.Vector3, t: number) => new THREE.Vector3().lerpVectors(a, b, ease(Math.min(1, Math.max(0, t))))
const w = (p: THREE.Vector3, up: number) => new THREE.Vector3(p.x, p.y + up, p.z)

const HOME = new THREE.Vector3(-0.2, 1.8, 0.5)
const ABOVE_PICK = w(PICK, 1.0), AT_PICK = w(PICK, WRIST_DOWN), LIFT = w(PICK, 1.1)
const ABOVE_PAD = w(PAD, 1.1), AT_PAD = w(PAD, WRIST_DOWN + 0.02)

/** wrist target, gripper opening and whether the cube is held, for time t in a loop */
function pose(t: number, slip: boolean) {
  let p: THREE.Vector3, grip = 0.34, held = false
  if (t < 1.6) p = lerpV(HOME, ABOVE_PICK, t / 1.6)
  else if (t < 2.6) p = lerpV(ABOVE_PICK, AT_PICK, t - 1.6)
  else if (t < 3.2) { p = AT_PICK; grip = 0.34 - 0.19 * ease((t - 2.6) / 0.6); held = true }
  else if (t < 4.2) { p = lerpV(AT_PICK, LIFT, t - 3.2); grip = 0.15; held = true }
  else if (t < 5.8) { p = lerpV(LIFT, ABOVE_PAD, (t - 4.2) / 1.6); grip = 0.15; held = true }
  else if (t < 6.8) { p = lerpV(ABOVE_PAD, AT_PAD, t - 5.8); grip = 0.15; held = true }
  else if (t < 7.3) { p = AT_PAD; grip = 0.15 + 0.19 * ease((t - 6.8) / 0.5) }
  else if (t < 8.3) p = lerpV(AT_PAD, ABOVE_PAD, t - 7.3)
  else p = lerpV(ABOVE_PAD, HOME, (t - 8.3) / 0.7)
  if (slip && t > 3.7) { held = false; grip = Math.min(0.34, 0.15 + 0.5 * (t - 3.7)) } // the grip lets go during the lift
  return { p, grip, held }
}

function Arm({ active }: { active: boolean }) {
  const yaw = useRef<THREE.Group>(null), upper = useRef<THREE.Group>(null), fore = useRef<THREE.Group>(null), hand = useRef<THREE.Group>(null)
  const f1 = useRef<THREE.Mesh>(null), f2 = useRef<THREE.Mesh>(null), cube = useRef<THREE.Mesh>(null), cubeMat = useRef<THREE.MeshStandardMaterial>(null)
  const clock = useRef({ t: 0, loop: 0, fall: 0 })

  useFrame((_, dt) => {
    if (!active) return
    const c = clock.current
    c.t += Math.min(dt, 0.05)
    if (c.t >= PERIOD) { c.t -= PERIOD; c.loop += 1; c.fall = 0 }
    const slip = c.loop % 3 === 2 // every third loop the cube slips out of the grip
    const { p, grip, held } = pose(c.t, slip)
    // planar two-link IK in the vertical plane through the base and the wrist target
    const dx = p.x, dz = p.z - 0, r = Math.hypot(dx, dz), h = p.y - SHOULDER_Y
    const d = Math.min(Math.hypot(r, h), L1 + L2 - 0.02)
    const a = Math.atan2(h, r) + Math.acos(THREE.MathUtils.clamp((L1 * L1 + d * d - L2 * L2) / (2 * L1 * d), -1, 1))
    const B = Math.acos(THREE.MathUtils.clamp((L1 * L1 + L2 * L2 - d * d) / (2 * L1 * L2), -1, 1))
    const rel = -(Math.PI - B)
    if (yaw.current) yaw.current.rotation.y = -Math.atan2(dz, dx)
    if (upper.current) upper.current.rotation.z = a
    if (fore.current) fore.current.rotation.z = rel
    if (hand.current) hand.current.rotation.z = -(a + rel) - Math.PI / 2
    if (f1.current) f1.current.position.z = grip
    if (f2.current) f2.current.position.z = -grip
    if (cube.current) {
      if (held) cube.current.position.set(p.x, p.y - WRIST_DOWN, p.z)
      else if (slip && c.t > 3.7 && c.t < 8.9) {
        c.fall = Math.min(c.fall + dt * 3.2, 2); const y = Math.max(PICK.y, cube.current.position.y - c.fall * dt * 2.4)
        cube.current.position.set(cube.current.position.x, y, cube.current.position.z)
        cube.current.rotation.z += dt * (y > PICK.y ? 2.5 : 0)
      } else if (c.t < 0.05 || (c.t > 8.9 && slip)) { cube.current.position.copy(PICK); cube.current.rotation.set(0, 0, 0) }
      else if (!held && !slip) cube.current.position.set(c.t < 3 ? PICK.x : PAD.x, PICK.y, c.t < 3 ? PICK.z : PAD.z)
      if (c.t < 0.05) { cube.current.position.copy(PICK); cube.current.rotation.set(0, 0, 0) }
    }
    if (cubeMat.current) cubeMat.current.emissive.setRGB(slip && c.t > 3.7 && c.t < 7 ? 0.6 : 0.08, 0.02, 0.01)
  })

  const metal = '#c9d4cc'
  return (
    <group>
      <mesh position={[0, 0.2, 0]}><cylinderGeometry args={[0.55, 0.7, 0.4, 40]} /><meshStandardMaterial color="#10171a" metalness={0.6} roughness={0.35} /></mesh>
      <group ref={yaw} position={[0, SHOULDER_Y, 0]}>
        <mesh><sphereGeometry args={[0.26, 24, 24]} /><meshStandardMaterial color="#f2b134" metalness={0.5} roughness={0.3} /></mesh>
        <group ref={upper}>
          <mesh position={[L1 / 2, 0, 0]}><boxGeometry args={[L1, 0.22, 0.26]} /><meshStandardMaterial color={metal} metalness={0.7} roughness={0.3} /></mesh>
          <group ref={fore} position={[L1, 0, 0]}>
            <mesh><sphereGeometry args={[0.2, 24, 24]} /><meshStandardMaterial color="#f2b134" metalness={0.5} roughness={0.3} /></mesh>
            <mesh position={[L2 / 2, 0, 0]}><boxGeometry args={[L2, 0.18, 0.22]} /><meshStandardMaterial color={metal} metalness={0.7} roughness={0.3} /></mesh>
            <group ref={hand} position={[L2, 0, 0]}>
              <mesh><sphereGeometry args={[0.14, 20, 20]} /><meshStandardMaterial color="#f2b134" metalness={0.5} roughness={0.3} /></mesh>
              <mesh position={[0.1, 0, 0]}><boxGeometry args={[0.08, 0.1, 0.8]} /><meshStandardMaterial color="#222c2a" metalness={0.6} roughness={0.4} /></mesh>
              {/* hand axis points down (local +x); fingers extend along it */}
              <mesh ref={f1} position={[0.3, 0, 0.34]}><boxGeometry args={[0.42, 0.1, 0.07]} /><meshStandardMaterial color="#dde4d9" metalness={0.6} roughness={0.3} /></mesh>
              <mesh ref={f2} position={[0.3, 0, -0.34]}><boxGeometry args={[0.42, 0.1, 0.07]} /><meshStandardMaterial color="#dde4d9" metalness={0.6} roughness={0.3} /></mesh>
            </group>
          </group>
        </group>
      </group>
      <mesh ref={cube} position={PICK.toArray()}><boxGeometry args={[0.3, 0.3, 0.3]} /><meshStandardMaterial ref={cubeMat} color="#ff6a47" roughness={0.5} emissive="#140503" /></mesh>
    </group>
  )
}

function Particles({ active }: { active: boolean }) {
  const ref = useRef<THREE.Points>(null)
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry(), n = 140, a = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) { a[i * 3] = (Math.random() - 0.5) * 9; a[i * 3 + 1] = Math.random() * 4.5; a[i * 3 + 2] = (Math.random() - 0.5) * 6 }
    g.setAttribute('position', new THREE.BufferAttribute(a, 3))
    return g
  }, [])
  useFrame((_, dt) => {
    if (!active || !ref.current) return
    const p = ref.current.geometry.attributes.position as THREE.BufferAttribute
    for (let i = 0; i < p.count; i++) { let y = p.getY(i) + dt * 0.12; if (y > 4.5) y = 0; p.setY(i, y) }
    p.needsUpdate = true
  })
  return <points ref={ref} geometry={geo}><pointsMaterial size={0.035} color="#f2b134" transparent opacity={0.55} depthWrite={false} /></points>
}

function Rig({ active }: { active: boolean }) {
  useFrame((s) => {
    if (!active) return
    s.camera.position.x += (s.pointer.x * 0.9 - s.camera.position.x) * 0.04
    s.camera.position.y += (2.3 + s.pointer.y * 0.4 - s.camera.position.y) * 0.04
    s.camera.lookAt(0, 0.9, 0)
  })
  return null
}

export default function HeroScene({ active }: { active: boolean }) {
  return (
    <Canvas dpr={[1, 1.5]} frameloop={active ? 'always' : 'never'} camera={{ position: [0, 2.4, 7.6], fov: 40 }} gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}>
      <ambientLight intensity={0.55} />
      <directionalLight position={[3, 6, 4]} intensity={1.6} />
      <pointLight position={[-3, 2.5, 2]} intensity={14} color="#f2b134" distance={9} />
      <pointLight position={[3, 1, 1]} intensity={8} color="#5be39a" distance={7} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]}><circleGeometry args={[4.6, 64]} /><meshStandardMaterial color="#0c1210" metalness={0.4} roughness={0.7} transparent opacity={0.9} /></mesh>
      <gridHelper args={[9, 18, '#1f2d27', '#16201c']} position={[0, 0.002, 0]} />
      <mesh position={[PAD.x, 0.01, PAD.z]} rotation={[-Math.PI / 2, 0, 0]}><ringGeometry args={[0.3, 0.46, 48]} /><meshBasicMaterial color="#5be39a" transparent opacity={0.9} /></mesh>
      <mesh position={[PICK.x, 0.005, PICK.z]} rotation={[-Math.PI / 2, 0, 0]}><ringGeometry args={[0.24, 0.27, 48]} /><meshBasicMaterial color="#f2b134" transparent opacity={0.5} /></mesh>
      <Arm active={active} />
      <Particles active={active} />
      <Rig active={active} />
    </Canvas>
  )
}
