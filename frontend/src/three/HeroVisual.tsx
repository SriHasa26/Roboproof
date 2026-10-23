import { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { useMotionPrefs } from '../motion'

const Scene = lazy(() => import('./HeroScene'))

/** Static illustration: used while the 3D chunk loads, when WebGL is unavailable, and under reduced motion. */
export function HeroFallback() {
  return (
    <svg viewBox="0 0 480 360" className="h-full w-full" role="img" aria-label="Illustration of a robot arm placing a cube on a target pad">
      <defs>
        <linearGradient id="hf-g" x1="0" x2="1"><stop offset="0" stopColor="#f2b134" /><stop offset="1" stopColor="#ffd479" /></linearGradient>
        <radialGradient id="hf-glow"><stop offset="0" stopColor="#5be39a" stopOpacity=".5" /><stop offset="1" stopColor="#5be39a" stopOpacity="0" /></radialGradient>
      </defs>
      <ellipse cx="340" cy="296" rx="70" ry="18" fill="url(#hf-glow)" />
      <ellipse cx="340" cy="296" rx="46" ry="11" fill="none" stroke="#5be39a" strokeWidth="2" />
      <ellipse cx="150" cy="318" rx="70" ry="14" fill="#0e1311" stroke="rgba(255,255,255,.12)" />
      <path d="M150 312 L190 220 L290 160" fill="none" stroke="url(#hf-g)" strokeWidth="16" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="190" cy="220" r="12" fill="#0b0f0e" stroke="#f2b134" strokeWidth="3" />
      <circle cx="290" cy="160" r="10" fill="#0b0f0e" stroke="#f2b134" strokeWidth="3" />
      <path d="M290 160 L318 196 M290 160 L338 180" stroke="#dde4d9" strokeWidth="6" strokeLinecap="round" fill="none" />
      <rect x="312" y="204" width="34" height="34" rx="4" fill="#ff6a47" opacity=".9" transform="rotate(8 329 221)" />
    </svg>
  )
}

function hasWebGL(): boolean {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')) } catch { return false }
}

/** 3D hero: lazy-loaded, paused when off-screen, static pose under reduced motion. */
export default function HeroVisual() {
  const { reduce } = useMotionPrefs()
  const ref = useRef<HTMLDivElement>(null)
  const [visible, setVisible] = useState(true)
  const [gl] = useState(() => typeof document !== 'undefined' && hasWebGL())
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting), { threshold: 0.05 })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  const use3d = gl && !reduce
  return (
    <div ref={ref} className="relative h-full w-full"><div className="h-full w-full [mask-image:radial-gradient(closest-side,#000_62%,transparent_100%)] [-webkit-mask-image:radial-gradient(closest-side,#000_62%,transparent_100%)]">
      {use3d ? (
        <Suspense fallback={<HeroFallback />}><Scene active={visible} /></Suspense>
      ) : <HeroFallback />}
      </div>
      <p className="pointer-events-none absolute bottom-1 left-2 font-mono text-[10px] text-dim/80">illustrative animation, not simulation output</p>
    </div>
  )
}
