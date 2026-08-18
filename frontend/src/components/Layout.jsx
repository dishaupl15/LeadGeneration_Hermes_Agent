/**
 * Layout.jsx
 * ──────────
 * Shared application shell: clean top navigation + page content area.
 *
 * Navigation items (primary):
 *   Dashboard · Generate Leads · Leads · Follow-ups · History
 *
 * Right side:
 *   Notification bell · "More" dropdown (Social Leads, Lead Forms, Enrichment) · DB status dot
 *
 * All technical provider names (Google Maps, Reddit, CompanyEnrich, Serper,
 * Firecrawl, Origami, PDL…) are hidden from the primary UI — they are
 * implementation details, not user-facing features.
 */

import { useState, useRef, useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'
import NotificationBell from './NotificationBell'
import { healthCheck } from '../services/api'

/* ── DB status dot — tiny indicator, not a major nav item ─────────────────── */
function DbStatusDot() {
  const [ok, setOk] = useState(null)   // null = checking, true = ok, false = error
  useEffect(() => {
    healthCheck()
      .then(() => setOk(true))
      .catch(() => setOk(false))
    const id = setInterval(() => {
      healthCheck().then(() => setOk(true)).catch(() => setOk(false))
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  if (ok === null) return (
    <span className="w-2 h-2 rounded-full bg-slate-300 animate-pulse" title="Checking connection…" />
  )
  return (
    <span
      className={`w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-rose-400 animate-pulse'}`}
      title={ok ? 'Backend connected' : 'Backend unreachable'}
    />
  )
}

/* ── "More" dropdown — secondary features ──────────────────────────────────── */
function MoreMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-semibold
                    border transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-indigo-300
                    ${open
                      ? 'border-indigo-300 bg-indigo-50 text-indigo-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 hover:border-slate-300'}`}
      >
        More
        <svg className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`}
             fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-52 bg-white rounded-xl
                        shadow-xl border border-slate-200 overflow-hidden py-1">
          <p className="px-3 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-widest">
            Lead Sources
          </p>
          <Link to="/social-leads"
            onClick={() => setOpen(false)}
            className="flex items-center gap-3 px-3 py-2.5 text-sm text-slate-700
                       hover:bg-indigo-50 hover:text-indigo-700 transition-colors">
            <svg className="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            Social Leads
          </Link>
          <Link to="/forms"
            onClick={() => setOpen(false)}
            className="flex items-center gap-3 px-3 py-2.5 text-sm text-slate-700
                       hover:bg-indigo-50 hover:text-indigo-700 transition-colors">
            <svg className="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
            </svg>
            Lead Forms
          </Link>
        </div>
      )}
    </div>
  )
}

/* ── Mobile nav overlay ────────────────────────────────────────────────────── */
function MobileNav({ isOpen, onClose, location }) {
  const navLinks = [
    { to: '/dashboard', label: 'Dashboard',      icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { to: '/generate',  label: 'Generate Leads', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
    { to: '/',          label: 'Leads',           icon: 'M4 6h16M4 10h16M4 14h16M4 18h16' },
    { to: '/follow-ups',label: 'Follow-ups',      icon: 'M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z' },
    { to: '/history',   label: 'History',         icon: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z' },
  ]

  if (!isOpen) return null
  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="absolute left-0 top-0 bottom-0 w-64 bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-xl bg-indigo-600 flex items-center justify-center shadow-md">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
            </div>
            <span className="text-sm font-bold text-slate-900">LeadCRM</span>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        {/* Links */}
        <nav className="flex-1 overflow-y-auto py-3">
          {navLinks.map(link => {
            const active = link.to === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(link.to)
            return (
              <Link key={link.to} to={link.to} onClick={onClose}
                className={`flex items-center gap-3 px-5 py-3 text-sm font-semibold
                           transition-colors ${active
                             ? 'text-indigo-700 bg-indigo-50 border-r-2 border-indigo-600'
                             : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'}`}>
                <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={link.icon}/>
                </svg>
                {link.label}
              </Link>
            )
          })}

          <div className="border-t border-slate-100 mt-3 pt-3 px-5">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">More</p>
            {[
              { to: '/social-leads', label: 'Social Leads' },
              { to: '/forms',        label: 'Lead Forms' },
            ].map(link => (
              <Link key={link.to} to={link.to} onClick={onClose}
                className="flex items-center px-2 py-2.5 text-sm text-slate-600
                           hover:text-indigo-700 hover:bg-indigo-50 rounded-lg transition-colors">
                {link.label}
              </Link>
            ))}
          </div>
        </nav>

        {/* Status */}
        <div className="px-5 py-4 border-t border-slate-100 flex items-center gap-2">
          <DbStatusDot />
          <span className="text-xs text-slate-400">System status</span>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   MAIN LAYOUT COMPONENT
   ══════════════════════════════════════════════════════════════════════════════ */
export default function Layout({
  children,
  followUpCategory = null,
  followUpRefreshTick = 0,
  onOpenFollowUps = null,
  onNavigateToLead = null,
}) {
  const location = useLocation()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const navLinks = [
    { to: '/dashboard', label: 'Dashboard',      exact: true  },
    { to: '/generate',  label: 'Generate Leads', exact: false },
    { to: '/',          label: 'Leads',           exact: true  },
    { to: '/follow-ups',label: 'Follow-ups',      exact: false },
    { to: '/history',   label: 'History',         exact: false },
  ]

  const isActive = (link) => {
    if (link.exact) return location.pathname === link.to
    return location.pathname.startsWith(link.to)
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="h-14 flex items-center justify-between gap-4">

            {/* Left: logo + primary nav */}
            <div className="flex items-center gap-6 min-w-0">
              {/* Logo */}
              <Link to="/dashboard" className="flex items-center gap-2.5 flex-shrink-0">
                <div className="w-8 h-8 rounded-xl bg-indigo-600 flex items-center justify-center shadow-md">
                  <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                      d="M13 10V3L4 14h7v7l9-11h-7z"/>
                  </svg>
                </div>
                <span className="text-sm font-bold text-slate-900">LeadCRM</span>
              </Link>

              {/* Desktop primary navigation */}
              <nav className="hidden lg:flex items-center gap-0.5">
                {navLinks.map(link => {
                  const active = isActive(link)
                  return (
                    <Link
                      key={link.to}
                      to={link.to}
                      className={`px-3.5 py-1.5 rounded-lg text-sm font-medium transition-all duration-150
                                  ${active
                                    ? 'text-indigo-700 bg-indigo-50'
                                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100'}`}
                    >
                      {link.label}
                    </Link>
                  )
                })}
              </nav>
            </div>

            {/* Right: notification + more + db status */}
            <div className="flex items-center gap-2 flex-shrink-0">
              {/* Notification bell */}
              <NotificationBell
                category={followUpCategory}
                refreshTick={followUpRefreshTick}
                onOpenPanel={onOpenFollowUps}
                onNavigateLead={onNavigateToLead}
              />

              {/* More menu — social leads, forms, origami */}
              <div className="hidden sm:block">
                <MoreMenu />
              </div>

              {/* DB status */}
              <div className="hidden sm:flex items-center gap-1.5 px-2 py-1 rounded-lg
                              border border-slate-200 bg-white">
                <DbStatusDot />
                <span className="text-[11px] text-slate-400 font-medium hidden md:inline">Live</span>
              </div>

              {/* Mobile hamburger */}
              <button
                onClick={() => setMobileNavOpen(true)}
                className="lg:hidden inline-flex items-center justify-center w-8 h-8 rounded-lg
                           border border-slate-200 text-slate-600 hover:bg-slate-50"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Mobile nav overlay */}
      <MobileNav
        isOpen={mobileNavOpen}
        onClose={() => setMobileNavOpen(false)}
        location={location}
      />

      {/* ── Page content ─────────────────────────────────────────────────── */}
      <main className="flex-1">
        {children}
      </main>
    </div>
  )
}
