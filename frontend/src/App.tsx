import { Component, ReactNode } from 'react'
import { HashRouter, Link, NavLink, Route, Routes } from 'react-router-dom'
import { useData, IndexItem } from './lib'
import About from './pages/About'
import Overview from './pages/Overview'
import RunPage from './pages/Run'
import TrapPage from './pages/Trap'

class Boundary extends Component<{ children: ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: unknown) { return { err: String(e) } }
  render() {
    return this.state.err
      ? <p className="rounded border border-verm/50 p-4 font-mono text-sm text-verm">This page hit a data problem and could not render: {this.state.err}</p>
      : this.props.children
  }
}

const nav = 'rounded-sm px-3 py-1.5 font-mono text-xs uppercase tracking-widest transition-colors'

function Runs() {
  const { data } = useData<IndexItem[]>('index.json')
  return (
    <div className="rise">
      <h1 className="mb-6 font-display text-5xl font-black uppercase">All recorded runs</h1>
      <ul className="panel divide-y divide-[#1f2924] rounded">
        {(data ?? []).map((r) => (
          <li key={r.id}><Link to={`/run/${r.id}`} className="flex flex-wrap items-center gap-3 p-4 hover:bg-white/[.03]">
            <span className="font-mono text-sm">{r.id}</span>
            <span className="font-mono text-[11px] uppercase text-dim">{r.badges.mode} | pipeline {r.badges.pipeline_version} | seed {r.master_seed ?? 'not recorded'}</span>
            <span className={`ml-auto font-display text-xl font-extrabold uppercase ${r.verdict === 'VERIFIED' ? 'text-phos' : r.verdict === 'FAILED' ? 'text-verm' : 'text-amber'}`}>{r.verdict}</span>
          </Link></li>
        ))}
      </ul>
    </div>
  )
}

export default function App() {
  return (
    <HashRouter>
      <div className="border-b border-amber/30 bg-amber/10 px-4 py-1.5 text-center font-mono text-[11px] uppercase tracking-wider text-amber">
        Simulation only &middot; simulations ran in a LOCAL container, not on Nebius Serverless Jobs &middot; recorded real runs &middot; cost figures are estimates
      </div>
      <nav className="sticky top-0 z-20 border-b hair bg-ink/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-1 px-4 py-2">
          <Link to="/" className="mr-4 font-display text-2xl font-black uppercase tracking-wider">Robo<span className="text-amber">Proof</span></Link>
          {[['/', 'Overview'], ['/runs', 'Runs'], ['/trap', 'Scripted trap'], ['/about', 'Limits']].map(([to, l]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `${nav} ${isActive ? 'bg-amber text-ink' : 'text-dim hover:text-text'}`}>{l}</NavLink>
          ))}
        </div>
      </nav>
      <main className="mx-auto max-w-6xl px-4 pb-24 pt-10">
        <Boundary><Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/run/:id" element={<RunPage />} />
          <Route path="/trap" element={<TrapPage />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<p className="font-mono text-sm text-dim">Page not found. <Link className="text-amber underline" to="/">Overview</Link></p>} />
        </Routes></Boundary>
      </main>
      <footer className="border-t hair px-4 py-6 text-center font-mono text-[11px] text-dim">
        RoboProof &middot; MIT licence &middot; NVIDIA Nemotron models via Nebius Token Factory &middot; every number is read from recorded artifacts
      </footer>
    </HashRouter>
  )
}
