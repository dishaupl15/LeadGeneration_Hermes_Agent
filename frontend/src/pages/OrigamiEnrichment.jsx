/**
 * OrigamiEnrichment.jsx
 * ──────────────────────
 * Standalone Origami people-enrichment page.
 *
 * Features
 * ────────
 *  - Module health card (key configured? base URL? limits?)
 *  - Live auth-test button
 *  - Single company contact search form
 *  - Results panel: tiered contacts table with confidence bars
 *  - Coverage stats panel (live from DB via existing /leads/origami-stats)
 *
 * Removal
 * ───────
 *  Delete this file + remove the Route in App.jsx + remove the nav button
 *  in LeadGeneration.jsx. Nothing else is affected.
 */

import { useState, useEffect, useCallback } from 'react'
import {
  getOrigamiHealth,
  testOrigamiAuth,
  origamiSearchContacts,
  getOrigamiStats,
} from '../services/api'

// ── Tier badge ─────────────────────────────────────────────────────────────────
const TIER_STYLES = {
  1: { bg: 'bg-violet-100 text-violet-700 border-violet-200',  dot: 'bg-violet-500' },
  2: { bg: 'bg-indigo-100 text-indigo-700 border-indigo-200',  dot: 'bg-indigo-500' },
  3: { bg: 'bg-sky-100 text-sky-700 border-sky-200',           dot: 'bg-sky-500'    },
  4: { bg: 'bg-amber-100 text-amber-700 border-amber-200',     dot: 'bg-amber-500'  },
  5: { bg: 'bg-slate-100 text-slate-600 border-slate-200',     dot: 'bg-slate-400'  },
}

function TierBadge({ tier, label }) {
  const s = TIER_STYLES[tier] || TIER_STYLES[5]
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border ${s.bg}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} />
      {label}
    </span>
  )
}

// ── Confidence bar ─────────────────────────────────────────────────────────────
function ConfBar({ value }) {
  const pct = Math.round((value ?? 0) * 100)
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 60 ? 'bg-amber-400' : 'bg-rose-400'
  return (
    <div className="flex items-center gap-1.5 min-w-[70px]">
      <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-slate-500 w-7 text-right">{pct}%</span>
    </div>
  )
}

// ── Founder status badge ───────────────────────────────────────────────────────
function FounderStatusBadge({ status }) {
  const map = {
    found:                { cls: 'bg-emerald-100 text-emerald-700 border-emerald-200', label: '✅ Founder found'         },
    found_decision_maker: { cls: 'bg-violet-100 text-violet-700 border-violet-200',   label: '💼 Decision maker found'  },
    not_found:            { cls: 'bg-amber-100 text-amber-700 border-amber-200',       label: '🔍 Not found'             },
    skipped:              { cls: 'bg-slate-100 text-slate-500 border-slate-200',       label: '⏭ Skipped (no key)'      },
    error:                { cls: 'bg-rose-100 text-rose-700 border-rose-200',          label: '❌ Error'                 },
  }
  const s = map[status] || map.error
  return (
    <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold border ${s.cls}`}>
      {s.label}
    </span>
  )
}

// ── Progress bar (for stats panel) ────────────────────────────────────────────
function PctBar({ pct, color = 'bg-violet-500' }) {
  const p = Math.min(100, Math.max(0, pct ?? 0))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${p}%` }} />
      </div>
      <span className="text-[11px] font-bold text-slate-700 w-10 text-right">{p}%</span>
    </div>
  )
}

// ── Status dot (for stats panel) ──────────────────────────────────────────────
function StatusDot({ label, count, dot }) {
  if (!count) return null
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {label}: <strong className="text-slate-700">{count}</strong>
    </span>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function OrigamiEnrichment() {
  // ── Health & auth state ──────────────────────────────────────────────────────
  const [health,      setHealth]      = useState(null)
  const [healthLoading, setHealthLoading] = useState(true)
  const [authResult,  setAuthResult]  = useState(null)
  const [authTesting, setAuthTesting] = useState(false)

  // ── Search form state ────────────────────────────────────────────────────────
  const [companyName, setCompanyName] = useState('')
  const [domain,      setDomain]      = useState('')
  const [website,     setWebsite]     = useState('')
  const [location,    setLocation]    = useState('')
  const [category,    setCategory]    = useState('')

  // ── Search result state ──────────────────────────────────────────────────────
  const [searching,   setSearching]   = useState(false)
  const [result,      setResult]      = useState(null)
  const [searchError, setSearchError] = useState('')

  // ── DB coverage stats ────────────────────────────────────────────────────────
  const [stats,        setStats]       = useState(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError,   setStatsError]   = useState('')

  // ── Load health on mount ─────────────────────────────────────────────────────
  useEffect(() => {
    setHealthLoading(true)
    getOrigamiHealth()
      .then(setHealth)
      .catch(() => setHealth(null))
      .finally(() => setHealthLoading(false))
  }, [])

  // ── Load coverage stats on mount ─────────────────────────────────────────────
  const loadStats = useCallback(() => {
    setStatsLoading(true)
    setStatsError('')
    getOrigamiStats(null)
      .then(setStats)
      .catch(err => setStatsError(err.message || 'Failed to load stats'))
      .finally(() => setStatsLoading(false))
  }, [])

  useEffect(() => { loadStats() }, [loadStats])

  // ── Auth test ─────────────────────────────────────────────────────────────────
  const handleAuthTest = async () => {
    setAuthTesting(true)
    setAuthResult(null)
    try {
      const res = await testOrigamiAuth()
      setAuthResult(res)
    } catch (err) {
      setAuthResult({ ORIGAMI_AUTHENTICATION: 'FAILED', message: err.message })
    } finally {
      setAuthTesting(false)
    }
  }

  // ── Search ────────────────────────────────────────────────────────────────────
  const handleSearch = async (e) => {
    e.preventDefault()
    if (!companyName.trim()) return
    setSearching(true)
    setResult(null)
    setSearchError('')
    try {
      const res = await origamiSearchContacts({
        company_name: companyName.trim(),
        domain:   domain.trim()   || null,
        website:  website.trim()  || null,
        location: location.trim() || null,
        category: category.trim() || null,
      })
      setResult(res)
    } catch (err) {
      setSearchError(err.message || 'Search failed.')
    } finally {
      setSearching(false)
    }
  }

  const handleClear = () => {
    setResult(null)
    setSearchError('')
    setCompanyName('')
    setDomain('')
    setWebsite('')
    setLocation('')
    setCategory('')
  }

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-slate-100">

      {/* ── TOP NAV ────────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="h-16 flex items-center justify-between">

            {/* Brand + breadcrumb */}
            <div className="flex items-center gap-3">
              <a href="/" className="flex items-center gap-2.5 group">
                <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-md shadow-indigo-200">
                  <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z"/>
                  </svg>
                </div>
                <span className="text-sm font-semibold text-slate-500 group-hover:text-indigo-600 transition-colors">LeadCRM</span>
              </a>
              <span className="text-slate-300">/</span>
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-lg bg-fuchsia-100 flex items-center justify-center">
                  <svg className="w-4 h-4 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
                         m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
                         A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
                         c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                  </svg>
                </div>
                <span className="text-sm font-bold text-slate-800">Origami Enrichment</span>
              </div>
            </div>

            {/* Back button */}
            <a
              href="/"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                         border border-slate-200 bg-white text-slate-600
                         hover:bg-slate-50 hover:border-slate-300
                         text-xs font-semibold transition-colors"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/>
              </svg>
              Back to CRM
            </a>
          </div>
        </div>
      </header>

      {/* ── PAGE CONTENT ───────────────────────────────────────────────────── */}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">

        {/* ── Row 1: Health card + Auth test card ──────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">

          {/* Health card */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded-lg bg-fuchsia-100 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </span>
              Module Health
            </h2>

            {healthLoading ? (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <svg className="w-4 h-4 animate-spin text-fuchsia-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
                Loading…
              </div>
            ) : health ? (
              <div className="space-y-2.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Status</span>
                  <span className={`px-2 py-0.5 rounded-full font-semibold border text-[10px] ${
                    health.configured
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                      : 'bg-rose-50 border-rose-200 text-rose-600'
                  }`}>
                    {health.configured ? '✅ Configured' : '❌ No API key'}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Base URL</span>
                  <span className="text-slate-700 font-mono text-[10px] truncate max-w-[180px]">{health.base_url}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Max contacts</span>
                  <span className="text-slate-700 font-semibold">{health.max_contacts}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-slate-500">Timeout</span>
                  <span className="text-slate-700 font-semibold">{health.timeout_seconds}s</span>
                </div>
                {!health.configured && (
                  <p className="mt-2 text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                    Set <code className="font-mono">ORIGAMI_API_KEY</code> in <code className="font-mono">backend/.env</code> and restart the server.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-400">Could not load health status.</p>
            )}
          </div>

          {/* Auth test card */}
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2 mb-4">
              <span className="w-6 h-6 rounded-lg bg-fuchsia-100 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"/>
                </svg>
              </span>
              Auth Test
            </h2>

            <p className="text-xs text-slate-400 mb-4">
              Sends a live probe to the Origami API to verify your key is accepted.
            </p>

            <button
              onClick={handleAuthTest}
              disabled={authTesting}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold
                         bg-fuchsia-600 text-white hover:bg-fuchsia-700 disabled:opacity-60
                         transition-colors focus:outline-none focus:ring-2 focus:ring-fuchsia-400"
            >
              {authTesting
                ? <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>Testing…</>
                : 'Run Auth Test'
              }
            </button>

            {authResult && (
              <div className={`mt-4 rounded-xl px-4 py-3 text-xs border ${
                authResult.ORIGAMI_AUTHENTICATION === 'SUCCESS'
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                  : 'bg-rose-50 border-rose-200 text-rose-700'
              }`}>
                <p className="font-semibold mb-1">
                  {authResult.ORIGAMI_AUTHENTICATION === 'SUCCESS' ? '✅ Authentication successful' : '❌ Authentication failed'}
                </p>
                <p>{authResult.message}</p>
                {authResult.ORIGAMI_HTTP_STATUS && (
                  <p className="mt-1 text-[10px] opacity-70">HTTP {authResult.ORIGAMI_HTTP_STATUS}</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* ── Row 2: Search form ────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2 mb-5">
            <span className="w-6 h-6 rounded-lg bg-fuchsia-100 flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
            </span>
            Find Decision-Makers
          </h2>

          <form onSubmit={handleSearch} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

              {/* Company name */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600">
                  Company Name <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  value={companyName}
                  onChange={e => setCompanyName(e.target.value)}
                  placeholder="e.g. ABC Realty"
                  required
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-800
                             placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-fuchsia-400
                             focus:border-transparent"
                />
              </div>

              {/* Domain */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600">Domain</label>
                <input
                  type="text"
                  value={domain}
                  onChange={e => setDomain(e.target.value)}
                  placeholder="e.g. abcrealty.com"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-800
                             placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-fuchsia-400
                             focus:border-transparent"
                />
              </div>

              {/* Location */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600">Location</label>
                <input
                  type="text"
                  value={location}
                  onChange={e => setLocation(e.target.value)}
                  placeholder="e.g. Mumbai, Maharashtra"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-800
                             placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-fuchsia-400
                             focus:border-transparent"
                />
              </div>

              {/* Category */}
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-semibold text-slate-600">Industry / Category</label>
                <input
                  type="text"
                  value={category}
                  onChange={e => setCategory(e.target.value)}
                  placeholder="e.g. Real Estate"
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm text-slate-800
                             placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-fuchsia-400
                             focus:border-transparent"
                />
              </div>
            </div>

            <div className="flex items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={searching || !companyName.trim()}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold
                           bg-fuchsia-600 text-white hover:bg-fuchsia-700 disabled:opacity-60
                           transition-colors focus:outline-none focus:ring-2 focus:ring-fuchsia-400 shadow-sm"
              >
                {searching
                  ? <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                    </svg>Searching…</>
                  : <><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
                           m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
                           A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
                           c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                    </svg>Search Contacts</>
                }
              </button>
              {(result || searchError) && (
                <button
                  type="button"
                  onClick={handleClear}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold border border-slate-200
                             text-slate-600 hover:bg-slate-50 transition-colors"
                >
                  Clear
                </button>
              )}
            </div>
          </form>
        </div>

        {/* ── Row 3: Search results ─────────────────────────────────────────── */}
        {searchError && (
          <div className="bg-rose-50 border border-rose-200 rounded-2xl px-5 py-4 flex items-start gap-3">
            <svg className="w-4 h-4 text-rose-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
            </svg>
            <div className="text-sm text-rose-700">
              <p className="font-semibold mb-0.5">Search failed</p>
              <p className="text-xs">{searchError}</p>
            </div>
          </div>
        )}

        {result && (
          <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">

            {/* Result header */}
            <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
              <div>
                <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                  <span className="w-6 h-6 rounded-lg bg-fuchsia-100 flex items-center justify-center">
                    <svg className="w-3.5 h-3.5 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                    </svg>
                  </span>
                  {result.company_name}
                </h2>
                <p className="text-xs text-slate-400 mt-0.5 ml-8">
                  {result.contacts_found} contact{result.contacts_found !== 1 ? 's' : ''} found
                  · {result.emails_found} email{result.emails_found !== 1 ? 's' : ''}
                  · {result.phones_found} phone{result.phones_found !== 1 ? 's' : ''}
                  {result.elapsed_seconds != null && ` · ${result.elapsed_seconds}s`}
                </p>
              </div>
              <FounderStatusBadge status={result.founder_status} />
            </div>

            {/* No results */}
            {result.contacts_found === 0 ? (
              <div className="text-center py-10 text-sm text-slate-400">
                <svg className="w-8 h-8 mx-auto mb-3 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                {result.error === 'no_key'
                  ? 'ORIGAMI_API_KEY not set. Configure it in backend/.env.'
                  : 'No contacts found for this company.'}
              </div>
            ) : (

              /* Contacts table */
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">#</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">Tier</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">Name</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">Title</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">Email</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">Phone</th>
                      <th className="text-left font-semibold text-slate-400 pb-2 pr-4">LinkedIn</th>
                      <th className="text-left font-semibold text-slate-400 pb-2">Confidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {result.contacts.map((c, i) => (
                      <tr key={i} className="hover:bg-slate-50 transition-colors">
                        <td className="py-3 pr-4 text-slate-400 font-mono">{i + 1}</td>
                        <td className="py-3 pr-4">
                          <TierBadge tier={c.tier} label={c.tier_label} />
                        </td>
                        <td className="py-3 pr-4 font-semibold text-slate-800 whitespace-nowrap">
                          {c.name || <span className="text-slate-300 italic">—</span>}
                        </td>
                        <td className="py-3 pr-4 text-slate-600">
                          {c.title || <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-3 pr-4">
                          {c.email
                            ? <a href={`mailto:${c.email}`}
                                 className="text-fuchsia-600 hover:underline font-mono text-[11px]">
                                {c.email}
                              </a>
                            : <span className="text-slate-300">—</span>
                          }
                        </td>
                        <td className="py-3 pr-4 text-slate-600 font-mono text-[11px]">
                          {c.phone || <span className="text-slate-300">—</span>}
                        </td>
                        <td className="py-3 pr-4">
                          {c.linkedin_url
                            ? <a href={c.linkedin_url} target="_blank" rel="noopener noreferrer"
                                 className="text-sky-500 hover:text-sky-700">
                                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                                  <path d="M19 0H5C2.2 0 0 2.2 0 5v14c0 2.8 2.2 5 5 5h14c2.8 0 5-2.2 5-5V5c0-2.8-2.2-5-5-5zM7 19H4v-9h3v9zM5.5 8.5C4.5 8.5 3.7 7.7 3.7 6.7S4.5 4.9 5.5 4.9s1.8.8 1.8 1.8-.8 1.8-1.8 1.8zM20 19h-3v-4.4c0-3.4-4-3.1-4 0V19h-3v-9h3v1.7c1.4-2.5 7-2.7 7 2.4V19z"/>
                                </svg>
                              </a>
                            : <span className="text-slate-300">—</span>
                          }
                        </td>
                        <td className="py-3">
                          <ConfBar value={c.confidence} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Row 4: DB Coverage Stats ─────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <span className="w-6 h-6 rounded-lg bg-fuchsia-100 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-fuchsia-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
                </svg>
              </span>
              Database Coverage Stats
              {statsLoading && (
                <svg className="w-3.5 h-3.5 animate-spin text-fuchsia-400 ml-1" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              )}
            </h2>
            <button
              onClick={loadStats}
              disabled={statsLoading}
              title="Refresh stats"
              className="w-6 h-6 rounded-full flex items-center justify-center
                         text-slate-400 hover:text-fuchsia-600 hover:bg-fuchsia-50
                         transition-colors disabled:opacity-40"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
            </button>
          </div>

          {statsError && (
            <p className="text-xs text-rose-600">{statsError}</p>
          )}

          {!statsLoading && !statsError && stats && (
            stats.total_leads === 0 ? (
              <p className="text-xs text-slate-400 italic">
                No leads in database yet. Generate leads first, then check coverage here.
              </p>
            ) : (
              <div className="space-y-4">
                {/* Origami enrichment bar */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] font-semibold text-slate-600">Origami Enriched</span>
                    <span className="text-[10px] text-slate-400">
                      {stats.origami_enriched ?? 0} / {stats.total_leads} companies
                    </span>
                  </div>
                  <PctBar pct={stats.origami_percent ?? 0} color="bg-fuchsia-500" />
                  {/* Status breakdown */}
                  {stats.status_breakdown && Object.keys(stats.status_breakdown).length > 0 && (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                      <StatusDot label="Enriched"        count={stats.status_breakdown.found}                  dot="bg-emerald-400" />
                      <StatusDot label="Decision Maker"  count={stats.status_breakdown.found_decision_maker}   dot="bg-fuchsia-400" />
                      <StatusDot label="Not Found"       count={stats.status_breakdown.not_found}              dot="bg-amber-400"   />
                      <StatusDot label="Skipped"         count={stats.status_breakdown.skipped}                dot="bg-slate-300"   />
                      <StatusDot label="Error"           count={stats.status_breakdown.error}                  dot="bg-rose-400"    />
                    </div>
                  )}
                </div>

                {/* Founder coverage bar */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] font-semibold text-slate-600">Founder Coverage</span>
                    <span className="text-[10px] text-slate-400">
                      {stats.founder_found ?? 0} / {stats.total_leads} companies
                    </span>
                  </div>
                  <PctBar pct={stats.founder_percent ?? 0} color="bg-indigo-500" />
                </div>

                {/* Email coverage bar */}
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] font-semibold text-slate-600">Email Coverage</span>
                    <span className="text-[10px] text-slate-400">
                      {stats.founder_email_found ?? 0} / {Math.max(stats.founder_found ?? 0, 1)} founders
                    </span>
                  </div>
                  <PctBar pct={stats.founder_email_percent ?? 0} color="bg-emerald-500" />
                </div>

                {/* Totals row */}
                <div className="pt-3 border-t border-slate-100 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
                  <span>Total leads: <strong className="text-slate-700">{stats.total_leads}</strong></span>
                  <span>Origami enriched: <strong className="text-fuchsia-700">{stats.origami_enriched ?? 0}</strong></span>
                  <span>Founders: <strong className="text-indigo-700">{stats.founder_found ?? 0}</strong></span>
                  <span>Emails: <strong className="text-emerald-700">{stats.founder_email_found ?? 0}</strong></span>
                </div>
              </div>
            )
          )}
        </div>

        {/* ── Row 5: How to remove this module ─────────────────────────────── */}
        <details className="bg-white rounded-2xl border border-slate-200 shadow-sm">
          <summary className="px-5 py-4 text-xs font-semibold text-slate-500 cursor-pointer
                              hover:text-slate-700 select-none list-none flex items-center gap-2">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
            How to remove this module
          </summary>
          <div className="px-5 pb-5 text-xs text-slate-500 space-y-2 border-t border-slate-100 pt-4">
            <p>This module is fully isolated. To remove it cleanly:</p>
            <ol className="list-decimal pl-4 space-y-1">
              <li>Delete <code className="font-mono bg-slate-100 px-1 rounded">backend/origami/</code> folder</li>
              <li>Remove from <code className="font-mono bg-slate-100 px-1 rounded">backend/app/main.py</code>:
                <pre className="mt-1 bg-slate-50 border border-slate-200 rounded p-2 font-mono text-[10px]">{`from origami.routes import router as origami_router\napp.include_router(origami_router)`}</pre>
              </li>
              <li>Delete <code className="font-mono bg-slate-100 px-1 rounded">frontend/src/pages/OrigamiEnrichment.jsx</code></li>
              <li>Remove the <code className="font-mono bg-slate-100 px-1 rounded">{`<Route path="/origami" ...>`}</code> from <code className="font-mono bg-slate-100 px-1 rounded">App.jsx</code></li>
              <li>Remove the Origami nav button from <code className="font-mono bg-slate-100 px-1 rounded">LeadGeneration.jsx</code></li>
            </ol>
            <p className="text-[11px] text-slate-400 mt-2">
              The existing enrichment pipeline (<code className="font-mono">origami_service.py</code> + leads routes) is completely unaffected.
            </p>
          </div>
        </details>

      </main>
    </div>
  )
}
