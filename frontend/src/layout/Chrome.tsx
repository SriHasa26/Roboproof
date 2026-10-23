import { useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useMotionPrefs, usePageTitle } from '../motion'

export function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="RoboProof home">
      <svg viewBox="0 0 64 64" width="28" height="28" aria-hidden><rect width="64" height="64" rx="14" fill="#0d1210" stroke="rgba(255,255,255,.12)" />
        <path d="M14 46V22l18-8 18 8v24l-18 8z" fill="none" stroke="#f2b134" strokeWidth="4" strokeLinejoin="round" />
        <path d="M23 33l6 6 13-14" fill="none" stroke="#5be39a" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <span className="font-display text-xl font-extrabold tracking-tight">Robo<span className="text-amber">Proof</span></span>
    </Link>
  )
}

const LINKS: [string, string][] = [['/results', 'Results'], ['/runs', 'Runs'], ['/trap', 'Scripted trap'], ['/about', 'Limits']]
const lk = ({ isActive }: { isActive: boolean }) =>
  `rounded-full px-3.5 py-1.5 text-sm transition-colors ${isActive ? 'bg-white/10 text-text' : 'text-dim hover:bg-white/5 hover:text-text'}`

export function Nav() {
  const [open, setOpen] = useState(false)
  return (
    <header className="sticky top-0 z-30 px-3 pt-3">
      <nav className="glass mx-auto flex max-w-6xl items-center gap-2 px-4 py-2.5" aria-label="Main">
        <Logo />
        <div className="ml-6 hidden items-center gap-1 md:flex">
          {LINKS.map(([to, l]) => <NavLink key={to} to={to} className={lk}>{l}</NavLink>)}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Link to="/live" className="btn btn-primary !px-4 !py-2 text-sm"><span className="h-2 w-2 rounded-full bg-[#1a1405]" aria-hidden />Run live</Link>
          <button className="btn btn-ghost !px-3 !py-2 md:hidden" aria-expanded={open} aria-label="Menu" onClick={() => setOpen((o) => !o)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>{open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}</svg>
          </button>
        </div>
      </nav>
      {open && (
        <div className="glass mx-auto mt-2 flex max-w-6xl flex-col gap-1 p-3 md:hidden">
          {LINKS.map(([to, l]) => <NavLink key={to} to={to} className={lk} onClick={() => setOpen(false)}>{l}</NavLink>)}
        </div>
      )}
    </header>
  )
}

export function Banner() {
  return (
    <div className="border-b border-amber/25 bg-amber/[.07] px-4 py-1.5 text-center font-mono text-[10.5px] uppercase tracking-wider text-amber">
      Simulation only &middot; simulations run in a LOCAL container, not on Nebius Serverless Jobs &middot; cost figures are estimates
    </div>
  )
}

export function Footer() {
  const { userReduce, setUserReduce, reduce } = useMotionPrefs()
  return (
    <footer className="mt-24 border-t hair px-4 py-10">
      <div className="mx-auto grid max-w-6xl gap-8 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-3 max-w-sm text-sm leading-relaxed text-dim">Built for the NVIDIA x Nebius Global AI Hackathon, Physical AI track. Simulation only, no hardware. Language models: NVIDIA Nemotron on Nebius Token Factory.</p>
        </div>
        <div className="text-sm">
          <div className="eyebrow mb-3">Explore</div>
          <ul className="space-y-2 text-dim">
            <li><Link className="hover:text-text" to="/results">Official results</Link></li>
            <li><Link className="hover:text-text" to="/live">Live console</Link></li>
            <li><Link className="hover:text-text" to="/trap">Scripted trap</Link></li>
            <li><Link className="hover:text-text" to="/about">Limits and honesty</Link></li>
          </ul>
        </div>
        <div className="text-sm">
          <div className="eyebrow mb-3">Project</div>
          <ul className="space-y-2 text-dim">
            <li>Source repository: link added at publication</li>
            <li>License: MIT</li>
            <li>
              <label className="flex cursor-pointer items-center gap-2">
                <input type="checkbox" className="h-4 w-4 accent-[#f2b134]" checked={userReduce} onChange={(e) => setUserReduce(e.target.checked)} />
                Reduce motion and 3D{reduce && !userReduce ? ' (on by system setting)' : ''}
              </label>
            </li>
          </ul>
        </div>
      </div>
    </footer>
  )
}

export function NotFound() {
  usePageTitle('Page not found')
  return (
    <div className="mx-auto max-w-xl py-24 text-center">
      <div className="font-mono text-sm text-amber">404</div>
      <h1 className="mt-2 font-display text-5xl font-extrabold">Nothing proven here.</h1>
      <p className="mt-3 text-dim">That page does not exist. The gate would call it UNVERIFIED.</p>
      <Link to="/" className="btn btn-primary mt-8">Back to the start</Link>
    </div>
  )
}
