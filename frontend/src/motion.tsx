import { ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { MotionConfig, animate, motion, useInView } from 'framer-motion'

/* ---- motion preferences: the OS setting OR the footer toggle ("Reduce motion and 3D") ---- */
type Prefs = { reduce: boolean; userReduce: boolean; setUserReduce: (v: boolean) => void }
const Ctx = createContext<Prefs>({ reduce: false, userReduce: false, setUserReduce: () => {} })
const KEY = 'roboproof.reduce'

export function MotionPrefs({ children }: { children: ReactNode }) {
  const [os, setOs] = useState(() => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)
  const [userReduce, setUser] = useState(() => { try { return localStorage.getItem(KEY) === '1' } catch { return false } })
  useEffect(() => {
    const m = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!m) return
    const f = () => setOs(m.matches)
    m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [])
  const reduce = os || userReduce
  useEffect(() => { document.documentElement.dataset.reduce = reduce ? '1' : '0' }, [reduce])
  const setUserReduce = useCallback((v: boolean) => { setUser(v); try { localStorage.setItem(KEY, v ? '1' : '0') } catch { /* storage unavailable */ } }, [])
  const value = useMemo(() => ({ reduce, userReduce, setUserReduce }), [reduce, userReduce, setUserReduce])
  return <Ctx.Provider value={value}><MotionConfig reducedMotion={reduce ? 'always' : 'user'}>{children}</MotionConfig></Ctx.Provider>
}
export const useMotionPrefs = () => useContext(Ctx)

/** Scroll-triggered fade and rise. Plain div when motion is reduced. */
export function Reveal({ children, delay = 0, y = 26, className = '', as = 'div' }: { children: ReactNode; delay?: number; y?: number; className?: string; as?: 'div' | 'li' | 'section' }) {
  const { reduce } = useMotionPrefs()
  const M = motion[as]
  if (reduce) { const T = as; return <T className={className}>{children}</T> }
  return (
    <M className={className} initial={{ opacity: 0, y }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: '-60px' }}
      transition={{ duration: 0.65, delay, ease: [0.2, 0.7, 0.2, 1] }}>{children}</M>
  )
}

/** Counts from 0 to `value` when scrolled into view; shows the final value at once when motion is reduced. */
export function CountUp({ value, format = (v: number) => String(Math.round(v)), duration = 1.4 }: { value: number; format?: (v: number) => string; duration?: number }) {
  const { reduce } = useMotionPrefs()
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true, margin: '-40px' })
  const [v, setV] = useState(reduce ? value : 0)
  useEffect(() => {
    if (reduce) { setV(value); return }
    if (!inView) return
    const c = animate(0, value, { duration, ease: [0.2, 0.7, 0.2, 1], onUpdate: setV })
    return () => c.stop()
  }, [inView, value, duration, reduce])
  return <span ref={ref} className="tick">{format(v)}</span>
}

export function usePageTitle(t: string) {
  useEffect(() => { document.title = t ? `${t} | RoboProof` : 'RoboProof: robot fixes you can trust' }, [t])
}

export function Skeleton({ className = 'h-24 w-full' }: { className?: string }) { return <div className={`skeleton ${className}`} aria-hidden /> }

/* ---- toasts ---- */
type Toast = { id: number; text: string; tone: 'info' | 'ok' | 'warn' }
const ToastCtx = createContext<(text: string, tone?: Toast['tone']) => void>(() => {})
export const useToast = () => useContext(ToastCtx)
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, set] = useState<Toast[]>([])
  const push = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = Date.now() + Math.random()
    set((s) => [...s.slice(-3), { id, text, tone }])
    setTimeout(() => set((s) => s.filter((t) => t.id !== id)), 4500)
  }, [])
  const color = { info: '#7cc4ff', ok: '#5be39a', warn: '#f2b134' }
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,22rem)] flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <motion.div key={t.id} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} className="glass pointer-events-auto px-4 py-3 text-sm" style={{ borderColor: `${color[t.tone]}66` }}>
            {t.text}
          </motion.div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
