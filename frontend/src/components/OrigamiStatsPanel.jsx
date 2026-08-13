/**
 * OrigamiStatsPanel
 *
 * Displays Origami enrichment coverage stats fetched live from the database.
 * Percentages are NEVER hardcoded — every number comes from GET /leads/origami-stats.
 *
 * Shows:
 *   Origami Status  — Enriched / Partial / Not Found / Failed counts
 *   Founder Coverage — Found: X / Y companies · X%
 *   Email Coverage   — Found: X / Y founders · X%
 */

import { useState, useEffect, useCallback } from 'react'
import { getOrigamiStats } from '../services/api'

/* ── Tiny progress bar ─────────────────────────────────────────────────── */
function PctBar({ pct, color = 'bg-violet-500' }) {
  const p = Math.min(100, Math.max(0, pct ?? 0))
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${p}%` }}
        />
      </div>
      <span className="text-[11px] font-bold text-slate-700 w-10 text-right">{p}%</span>
    </div>
  )
}

/* ── Status breakdown dot ──────────────────────────────────────────────── */
function StatusDot({ label, count, dot }) {
  if (!count) return null
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {label}: <strong className="text-slate-700">{count}</strong>
    </span>
  )
}

export default function OrigamiStatsPanel({ category = null, refreshTrigger = 0 }) {
  const [stats,   setStats]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState('')

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    getOrigamiStats(category)
      .then(res => { if (!cancelled) setStats(res) })
      .catch(err => { if (!cancelled) setError(err.message || 'Failed to load Origami stats.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [category])

  useEffect(load, [load, refreshTrigger])

  if (loading && !stats) {
    return (
      <div className="crm-card px-5 py-4 flex items-center gap-3 text-xs text-slate-400">
        <svg className="w-4 h-4 animate-spin text-violet-400 flex-shrink-0"
          fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
        </svg>
        Loading Origami coverage stats…
      </div>
    )
  }

  if (error) {
    return (
      <div className="crm-card px-5 py-3 flex items-center gap-2 text-[11px] text-rose-600">
        <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
        </svg>
        Could not load Origami stats: {error}
        <button onClick={load} className="ml-auto text-rose-500 hover:text-rose-700 underline">
          Retry
        </button>
      </div>
    )
  }

  if (!stats) return null

  const total          = stats.total_leads          ?? 0
  const enriched       = stats.origami_enriched     ?? 0
  const founderFound   = stats.founder_found        ?? 0
  const emailFound     = stats.founder_email_found  ?? 0
  const origamiPct     = stats.origami_percent      ?? 0
  const founderPct     = stats.founder_percent      ?? 0
  const emailPct       = stats.founder_email_percent ?? 0
  const breakdown      = stats.status_breakdown     ?? {}

  return (
    <div className="crm-card p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-violet-100 flex items-center justify-center flex-shrink-0">
            <svg className="w-4 h-4 text-violet-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
                   m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
                   A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
                   c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          Origami Coverage
          {loading && (
            <svg className="w-3.5 h-3.5 animate-spin text-violet-400 ml-1" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          )}
        </h3>
        <button
          onClick={load}
          disabled={loading}
          title="Refresh stats"
          className="w-6 h-6 rounded-full flex items-center justify-center
                     text-slate-400 hover:text-violet-600 hover:bg-violet-50
                     transition-colors disabled:opacity-40"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581
                 m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
          </svg>
        </button>
      </div>

      {total === 0 ? (
        <p className="text-xs text-slate-400 italic">
          No leads in database yet{category ? ` for "${category}"` : ''}.
          Generate leads first, then re-check Origami coverage.
        </p>
      ) : (
        <div className="space-y-4">

          {/* ── Row 1: Origami Status ─────────────────────────────────── */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] font-semibold text-slate-600">Origami Status</span>
              <span className="text-[10px] text-slate-400">{enriched} / {total} companies enriched</span>
            </div>
            <PctBar pct={origamiPct} color="bg-violet-500" />

            {/* Status breakdown dots */}
            {Object.keys(breakdown).length > 0 && (
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
                <StatusDot label="Enriched"   count={breakdown.found}                  dot="bg-emerald-400" />
                <StatusDot label="Decision Maker" count={breakdown.found_decision_maker} dot="bg-violet-400" />
                <StatusDot label="Not Found"  count={breakdown.not_found}              dot="bg-amber-400"   />
                <StatusDot label="Skipped"    count={breakdown.skipped}                dot="bg-slate-300"   />
                <StatusDot label="Error"      count={breakdown.error}                  dot="bg-rose-400"    />
              </div>
            )}
          </div>

          {/* ── Row 2: Founder Coverage ───────────────────────────────── */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] font-semibold text-slate-600">Founder Coverage</span>
              <span className="text-[10px] text-slate-400">
                Found: {founderFound} / {total}
              </span>
            </div>
            <PctBar pct={founderPct} color="bg-indigo-500" />
            <p className="mt-1 text-[10px] text-slate-400">
              {founderPct}% of companies have a named founder or decision-maker
            </p>
          </div>

          {/* ── Row 3: Email Coverage ─────────────────────────────────── */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] font-semibold text-slate-600">Email Coverage</span>
              <span className="text-[10px] text-slate-400">
                Found: {emailFound} / {Math.max(founderFound, 1)}
              </span>
            </div>
            <PctBar pct={emailPct} color="bg-emerald-500" />
            <p className="mt-1 text-[10px] text-slate-400">
              {emailPct}% of Origami-enriched companies have an email address
            </p>
          </div>

          {/* ── Totals row ────────────────────────────────────────────── */}
          <div className="pt-3 border-t border-slate-100 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-500">
            <span>Total leads: <strong className="text-slate-700">{total}</strong></span>
            <span>Origami enriched: <strong className="text-violet-700">{enriched}</strong></span>
            <span>Founders: <strong className="text-indigo-700">{founderFound}</strong></span>
            <span>Emails: <strong className="text-emerald-700">{emailFound}</strong></span>
          </div>
        </div>
      )}
    </div>
  )
}
