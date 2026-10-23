import { Component, ReactNode, Suspense, lazy, useEffect } from 'react'
import { HashRouter, Link, Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { useData, IndexItem } from './lib'
import { BackendProvider } from './backend'
import { MotionPrefs, Skeleton, ToastProvider, usePageTitle } from './motion'
import { Banner, Footer, Nav, NotFound } from './layout/Chrome'
import About from './pages/About'
import Landing from './pages/Landing'
import Results from './pages/Results'
import RunPage from './pages/Run'
import TrapPage from './pages/Trap'

const Live = lazy(() => import('./pages/Live'))
const LiveReport = lazy(() => import('./pages/LiveReport'))
const Playground = lazy(() => import('./pages/Playground'))

class Boundary extends Component<{ children: ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: unknown) { return { err: String(e) } }
  render() {
    return this.state.err
      ? <p className="glass border-verm/50 p-4 font-mono text-sm text-verm">This page hit a data problem and could not render: {this.state.err}</p>
      : this.props.children
  }
}

function Runs() {
  usePageTitle('Runs')
  const { data } = useData<IndexItem[]>('index.json')
  return (
    <div>
      <div className="eyebrow mb-3">recorded runs</div>
      <h1 className="mb-8 font-display">Every run on record</h1>
      {!data ? <Skeleton className="h-64" /> : (
        <ul className="glass divide-y divide-white/[.06]">
          {data.map((r) => (
            <li key={r.id}><Link to={`/runs/${r.id}`} className="flex flex-wrap items-center gap-3 p-4 transition-colors hover:bg-white/[.04]">
              <span className="font-mono text-sm">{r.id}</span>
              <span className="font-mono text-[11px] uppercase text-dim">{r.badges.mode} | pipeline {r.badges.pipeline_version} | seed {r.master_seed ?? 'not recorded'}</span>
              <span className={`ml-auto font-display text-xl font-bold ${r.verdict === 'VERIFIED' ? 'text-phos' : r.verdict === 'FAILED' ? 'text-verm' : 'text-amber'}`}>{r.verdict}</span>
            </Link></li>
          ))}
        </ul>
      )}
    </div>
  )
}

const OldRun = () => { const { id } = useParams(); return <Navigate to={`/runs/${id}`} replace /> }

function Pages() {
  const loc = useLocation()
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={loc.pathname} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.28 }}>
        <Boundary>
          <Suspense fallback={<Skeleton className="h-96" />}>
            <Routes location={loc}>
              <Route path="/" element={<Landing />} />
              <Route path="/results" element={<Results />} />
              <Route path="/runs" element={<Runs />} />
              <Route path="/runs/:id" element={<RunPage />} />
              <Route path="/run/:id" element={<OldRun />} />
              <Route path="/live" element={<Live />} />
              <Route path="/live/report/:id" element={<LiveReport />} />
              <Route path="/playground" element={<Playground />} />
              <Route path="/trap" element={<TrapPage />} />
              <Route path="/about" element={<About />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </Boundary>
      </motion.div>
    </AnimatePresence>
  )
}

function ScrollTop() { const { pathname } = useLocation(); useEffect(() => { window.scrollTo(0, 0) }, [pathname]); return null }

export default function App() {
  return (
    <MotionPrefs>
      <BackendProvider>
      <ToastProvider>
        <HashRouter>
          <div className="atmos" aria-hidden><div className="grid" /><div className="noise" /></div>
          <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-amber focus:px-3 focus:py-2 focus:text-ink">Skip to content</a>
          <Banner />
          <Nav />
          <ScrollTop />
          <main id="main" className="mx-auto max-w-6xl px-4 pb-8 pt-8">
            <Pages />
          </main>
          <Footer />
        </HashRouter>
      </ToastProvider>
      </BackendProvider>
    </MotionPrefs>
  )
}
