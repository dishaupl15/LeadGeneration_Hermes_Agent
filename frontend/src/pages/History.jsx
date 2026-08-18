/**
 * History.jsx  —  /history
 * ─────────────────────────
 * Clean history of all past lead-generation runs.
 * Legacy entries (no run_id) are shown inline as normal cards — no
 * confusing "Legacy Data" section that users don't understand.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import {
  getHistory,
  getHistoryRun,
  getHistoryRunLeads,
  getLegacyCategories,
  getLegacyCategoryLeads,
  buildAllCategoriesExcelUrl,
} from '../services/api'

const POLL_MS = 5000

/* ── helpers ────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    }).format(new Date(iso))
  } catch { return iso?.slice(0, 16) ?? '—' }
}
function fmtDur(s) {
  if (s == null) return null
  s = Math.round(s)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60 > 0 ? s % 60 + 's' : ''}`
}
function todayStr() { return new Date().toISOString().slice(0, 10) }
function isToday(iso) { return !!iso && iso.slice(0, 10) === todayStr() }

/* ── Status badge ───────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const cfg = {
    running:   { cls: 'bg-sky-50 border-sky-200 text-sky-700',            dot: 'bg-sky-400 animate-pulse', label: 'Running'   },
    completed: { cls: 'bg-emerald-50 border-emerald-200 text-emerald-700', dot: 'bg-emerald-400',          label: 'Done'      },
    failed:    { cls: 'bg-rose-50 border-rose-200 text-rose-700',          dot: 'bg-rose-400',              label: 'Failed'    },
    imported:  { cls: 'bg-slate-50 border-slate-200 text-slate-500',       dot: 'bg-slate-300',             label: 'Imported'  },
  }
  const { cls, dot, label } = cfg[status] ?? cfg.imported
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold ${cls}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot}`} />
      {label}
    </span>
  )
}

/* ── Run detail slide-in ────────────────────────────────────────────────── */
function RunDetailPanel({ runId, onClose, onViewLeads }) {
  const [run,     setRun]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [busy,    setBusy]    = useState(false)
  const logsEndRef = useRef(null)
  const pollRef    = useRef(null)

  const fetchRun = useCallback(async () => {
    try {
      const d = await getHistoryRun(runId)
      setRun(d.run); setError(null)
      if (d.run?.status === 'running') pollRef.current = setTimeout(fetchRun, POLL_MS)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [runId])

  useEffect(() => { fetchRun(); return () => clearTimeout(pollRef.current) }, [fetchRun])
  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [run?.logs?.length])

  const handleLoad = async () => {
    setBusy(true)
    try {
      const d = await getHistoryRunLeads(runId, { per_page: 500 })
      onViewLeads(d.leads ?? [], run.category)
    } catch (e) { alert(`Failed: ${e.message}`) }
    finally { setBusy(false) }
  }

  const stats = run?.statistics ?? {}

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md h-full bg-white shadow-2xl flex flex-col overflow-hidden z-10">

        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 flex-shrink-0">
          <button onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 transition-colors">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-bold text-slate-800 truncate">{run?.category ?? 'Generation Run'}</h3>
            <p className="text-[11px] text-slate-400">{fmtDate(run?.started_at)}</p>
          </div>
          {run && <StatusBadge status={run.status} />}
        </div>

        {loading && (
          <div className="flex-1 flex items-center justify-center">
            <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          </div>
        )}
        {error && !loading && (
          <div className="m-4 p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-700">{error}</div>
        )}

        {!loading && run && (
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">

            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Details</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100 text-xs">
                {[
                  ['Industry',  run.category],
                  ['Location',  [run.district, run.state].filter(Boolean).join(', ') || 'All India'],
                  ['Requested', run.requested_count ?? '—'],
                  ['Found',     <span className="font-bold text-emerald-600">{run.generated_count ?? '—'}</span>],
                  ['Duration',  fmtDur(run.duration_seconds) || '—'],
                  ['Started',   fmtDate(run.started_at)],
                ].map(([lbl, val]) => (
                  <div key={lbl} className="flex items-center justify-between py-2">
                    <span className="text-slate-500">{lbl}</span>
                    <span className="font-semibold text-slate-800">{val}</span>
                  </div>
                ))}
              </div>
            </section>

            {Object.keys(stats).length > 0 && (
              <section>
                <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Results</h4>
                <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100 text-xs">
                  {[
                    stats.leads_generated != null && ['New leads',  <span className="font-bold text-indigo-600">{stats.leads_generated}</span>],
                    stats.duplicates      != null && ['Duplicates', stats.duplicates],
                    stats.with_email      != null && ['With email', stats.with_email],
                    stats.with_phone      != null && ['With phone', stats.with_phone],
                  ].filter(Boolean).map(([lbl, val]) => (
                    <div key={lbl} className="flex items-center justify-between py-2">
                      <span className="text-slate-500">{lbl}</span>
                      <span className="font-semibold text-slate-800">{val}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}

            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">
                Logs
                {run.status === 'running' && (
                  <span className="ml-2 inline-flex items-center gap-1 text-sky-600 normal-case font-normal text-[10px]">
                    <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse"/> Live
                  </span>
                )}
              </h4>
              <div className="rounded-xl border border-slate-100 bg-slate-900/[0.03] px-3 py-2 max-h-52 overflow-y-auto">
                {(run.logs ?? []).length === 0
                  ? <p className="text-[11px] text-slate-400 italic py-3">No logs available.</p>
                  : (run.logs ?? []).map((e, i) => (
                    <div key={i} className="flex items-start gap-2 py-1 text-[11px] font-mono">
                      <span className="text-slate-400 flex-shrink-0 w-14">{e.timestamp}</span>
                      <span className="text-slate-600 leading-snug break-all">{e.message}</span>
                    </div>
                  ))
                }
                <div ref={logsEndRef} />
              </div>
            </section>

            {run.error_message && (
              <section>
                <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
                  {run.error_message}
                </div>
              </section>
            )}
          </div>
        )}

        {!loading && run && (
          <div className="flex-shrink-0 px-5 py-4 border-t border-slate-200">
            <button onClick={handleLoad}
              disabled={run.status !== 'completed' || !run.generated_count || busy}
              className="w-full inline-flex items-center justify-center gap-2 px-4 py-3
                         rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700
                         shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
              {busy
                ? <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg> Loading…</>
                : <>View {run.generated_count} Leads</>
              }
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Run card ───────────────────────────────────────────────────────────── */
function RunCard({ run, onViewDetails, onLoadData, isLoading }) {
  const isReddit   = run.source === 'reddit'
  const isImported = !!run.isImported
  const today      = isToday(run.started_at ?? run.newest_lead_at)
  const leadsCount = run.generated_count ?? run.total_leads ?? 0

  const accentBar =
    isImported          ? 'bg-slate-200' :
    run.status === 'completed' ? (isReddit ? 'bg-orange-400' : 'bg-emerald-400') :
    run.status === 'failed'    ? 'bg-rose-400' :
    'bg-sky-400'

  const canLoad = isImported
    ? leadsCount > 0
    : (run.status === 'completed' && leadsCount > 0)

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden
                    hover:shadow-sm hover:border-slate-300 transition-all">
      <div className={`h-0.5 w-full ${accentBar}`} />
      <div className="px-4 py-4">

        {/* Header */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
            {isReddit && !isImported && (
              <span className="flex-shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full
                               bg-orange-50 border border-orange-200 text-orange-700 text-[10px] font-bold">
                Reddit
              </span>
            )}
            {today && (
              <span className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full
                               bg-indigo-50 border border-indigo-200 text-indigo-700 text-[10px] font-bold">
                Today
              </span>
            )}
            <span className="text-sm font-bold text-slate-800 truncate">{run.category}</span>
          </div>
          <StatusBadge status={isImported ? 'imported' : run.status} />
        </div>

        {/* Lead count + location */}
        <div className="space-y-1 mb-3">
          {!isImported && (
            <div className="flex items-center gap-2 text-xs text-slate-600">
              <span><strong className="text-slate-800">{run.requested_count ?? '—'}</strong> requested</span>
              <span className="text-slate-300">·</span>
              <span>
                <strong className={
                  run.status === 'completed' ? 'text-emerald-600' :
                  run.status === 'failed'    ? 'text-rose-600' : 'text-sky-600'
                }>
                  {leadsCount}
                </strong> found
              </span>
            </div>
          )}
          {isImported && (
            <p className="text-xs text-slate-600">
              <strong className="text-slate-800">{leadsCount}</strong> leads
            </p>
          )}
          <div className="flex flex-wrap gap-x-2 text-[11px] text-slate-400">
            {(run.started_at || run.newest_lead_at) && (
              <span>{fmtDate(run.started_at ?? run.newest_lead_at)}</span>
            )}
            {fmtDur(run.duration_seconds) && (
              <span>{fmtDur(run.duration_seconds)}</span>
            )}
            {(run.state || run.district) && (
              <span>{[run.district, run.state].filter(Boolean).join(', ')}</span>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          {!isImported && (
            <button onClick={() => onViewDetails(run.run_id)}
              className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                         rounded-lg text-xs font-semibold border border-slate-200
                         bg-slate-50 text-slate-600 hover:bg-slate-100 transition-colors">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5
                     c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7
                     -4.477 0-8.268-2.943-9.542-7z"/>
              </svg>
              Details
            </button>
          )}
          <button
            onClick={() => onLoadData(run)}
            disabled={!canLoad || isLoading}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                       rounded-lg text-xs font-semibold border border-indigo-200
                       bg-indigo-50 text-indigo-700 hover:bg-indigo-100
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {isLoading
              ? <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg> Loading…</>
              : <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                </svg> View Leads</>
            }
          </button>
        </div>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════
   PAGE
   ══════════════════════════════════════════════════════════════════════════ */
export default function History() {
  const navigate = useNavigate()

  const [runs,         setRuns]         = useState([])
  const [legacyCats,   setLegacyCats]   = useState([])
  const [loading,      setLoading]      = useState(true)
  const [error,        setError]        = useState(null)
  const [search,       setSearch]       = useState('')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [detailRunId,  setDetailRunId]  = useState(null)
  const [loadingRunId, setLoadingRunId] = useState(null)
  const [loadingCat,   setLoadingCat]   = useState(null)
  const [refreshTick,  setRefreshTick]  = useState(0)
  const pollRef = useRef(null)

  /* ── fetch ────────────────────────────────────────────────────────────── */
  const fetchAll = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const [runsR, legR] = await Promise.allSettled([
        getHistory({ per_page: 200 }),
        getLegacyCategories(),
      ])
      if (runsR.status === 'fulfilled') {
        setRuns(runsR.value.runs ?? [])
        setError(null)
        if ((runsR.value.runs ?? []).some(r => r.status === 'running'))
          pollRef.current = setTimeout(() => fetchAll(true), POLL_MS)
      } else {
        setError(runsR.reason?.message || 'Could not load history.')
      }
      if (legR.status === 'fulfilled') setLegacyCats(legR.value.legacy_categories ?? [])
    } catch (e) {
      setError(e?.message || 'Could not load history.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    clearTimeout(pollRef.current)
    fetchAll()
    return () => clearTimeout(pollRef.current)
  }, [fetchAll, refreshTick])

  /* ── load handlers ────────────────────────────────────────────────────── */
  const handleLoadRun = useCallback(async (run) => {
    if (run.isImported) {
      setLoadingCat(run.category)
      try {
        const d = await getLegacyCategoryLeads(run.category, { per_page: 500 })
        navigate('/', { state: { historyLeads: d.leads ?? [], historyLabel: run.category } })
      } catch (e) { alert(`Failed: ${e.message}`) }
      finally { setLoadingCat(null) }
      return
    }
    setLoadingRunId(run.run_id)
    try {
      const d = await getHistoryRunLeads(run.run_id, { per_page: 500 })
      navigate('/', { state: { historyLeads: d.leads ?? [], historyLabel: run.category } })
    } catch (e) { alert(`Failed: ${e.message}`) }
    finally { setLoadingRunId(null) }
  }, [navigate])

  const handleViewLeads = useCallback((leads, cat) => {
    navigate('/', { state: { historyLeads: leads, historyLabel: cat } })
  }, [navigate])

  /* ── merge runs + legacy into one list ────────────────────────────────── */
  const allItems = useMemo(() => {
    const runCats = new Set(runs.map(r => r.category?.toLowerCase()))
    const legacyItems = legacyCats
      .filter(lc => !runCats.has(lc.category?.toLowerCase()))
      .map(lc => ({
        run_id:         `legacy_${lc.category}`,
        category:       lc.category,
        generated_count: lc.total_leads,
        total_leads:    lc.total_leads,
        status:         'completed',
        started_at:     null,
        newest_lead_at: lc.newest_lead_at ?? null,
        isImported:     true,
      }))
    return [...runs.map(r => ({ ...r, isImported: false })), ...legacyItems]
  }, [runs, legacyCats])

  /* ── filter ───────────────────────────────────────────────────────────── */
  const filtered = useMemo(() => {
    let list = allItems
    if (sourceFilter === 'business') list = list.filter(r => r.source !== 'reddit' && !r.isImported)
    if (sourceFilter === 'reddit')   list = list.filter(r => r.source === 'reddit')
    const q = search.trim().toLowerCase()
    if (q) list = list.filter(r =>
      r.category?.toLowerCase().includes(q) ||
      r.state?.toLowerCase().includes(q) ||
      r.district?.toLowerCase().includes(q)
    )
    return list
  }, [allItems, sourceFilter, search])

  const todayItems = filtered.filter(r => isToday(r.started_at ?? r.newest_lead_at))
  const olderItems = filtered.filter(r => !isToday(r.started_at ?? r.newest_lead_at))
  const hasRunning = runs.some(r => r.status === 'running')
  const totalLeads = allItems.reduce((s, r) => s + (r.generated_count ?? r.total_leads ?? 0), 0)

  /* ── render ───────────────────────────────────────────────────────────── */
  return (
    <Layout
      followUpRefreshTick={refreshTick}
      onOpenFollowUps={() => navigate('/follow-ups')}
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* Page header */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
          <div>
            <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              Lead Generation History
              {hasRunning && (
                <span className="inline-flex items-center gap-1 text-xs font-medium
                                 text-sky-600 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded-full">
                  <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse"/>
                  In Progress
                </span>
              )}
            </h1>
            <p className="text-sm text-slate-500 mt-1">
              {loading ? 'Loading…' : (
                <>
                  {allItems.length} search{allItems.length !== 1 ? 'es' : ''}
                  {totalLeads > 0 && (
                    <> · <strong className="text-slate-700">{totalLeads.toLocaleString()}</strong> leads total</>
                  )}
                </>
              )}
            </p>
          </div>

          <div className="flex items-center gap-2">
            <a href={buildAllCategoriesExcelUrl()} download
              className="btn-secondary px-3 py-2 text-xs gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              Export All
            </a>
            <button onClick={() => setRefreshTick(t => t + 1)} disabled={loading}
              className="btn-secondary px-3 py-2 text-xs gap-1.5 disabled:opacity-40">
              <svg className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}
                   fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
              Refresh
            </button>
          </div>
        </div>

        {/* Search + filter bar */}
        <div className="flex flex-wrap gap-3 mb-5">
          <div className="relative flex-1 min-w-[180px]">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
              <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
            </div>
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search by industry or location…"
              className="crm-input pl-9 text-sm w-full" />
            {search && (
              <button onClick={() => setSearch('')}
                className="absolute inset-y-0 right-2.5 flex items-center text-slate-400 hover:text-slate-600">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            )}
          </div>

          <div className="flex gap-1.5">
            {[['all', 'All'], ['business', 'Business'], ['reddit', 'Reddit']].map(([val, lbl]) => (
              <button key={val} onClick={() => setSourceFilter(val)}
                className={`px-3 py-2 rounded-lg text-xs font-semibold border transition-all
                            ${sourceFilter === val
                              ? 'bg-indigo-600 border-indigo-600 text-white'
                              : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                {lbl}
              </button>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-sm text-rose-700 mb-4">
            {error}
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1,2,3,4,5,6].map(i => (
              <div key={i} className="bg-white rounded-xl border border-slate-200 p-4 space-y-3">
                <div className="shimmer h-4 w-24 rounded"/>
                <div className="shimmer h-3 w-40 rounded"/>
                <div className="shimmer h-8 w-full rounded-lg mt-2"/>
              </div>
            ))}
          </div>
        )}

        {/* Empty */}
        {!loading && filtered.length === 0 && (
          <div className="text-center py-20">
            <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-4">
              <svg className="w-7 h-7 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
            </div>
            <p className="text-base font-semibold text-slate-600">No history yet</p>
            <p className="text-sm text-slate-400 mt-1">
              {search ? `No results for "${search}"` : 'Generate leads to see your activity here.'}
            </p>
          </div>
        )}

        {/* Today */}
        {!loading && todayItems.length > 0 && (
          <div className="mb-7">
            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Today</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {todayItems.map(run => (
                <RunCard
                  key={run.run_id}
                  run={run}
                  onViewDetails={setDetailRunId}
                  onLoadData={handleLoadRun}
                  isLoading={
                    run.isImported
                      ? loadingCat === run.category
                      : loadingRunId === run.run_id
                  }
                />
              ))}
            </div>
          </div>
        )}

        {/* Earlier */}
        {!loading && olderItems.length > 0 && (
          <div>
            {todayItems.length > 0 && (
              <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">Earlier</p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {olderItems.map(run => (
                <RunCard
                  key={run.run_id}
                  run={run}
                  onViewDetails={setDetailRunId}
                  onLoadData={handleLoadRun}
                  isLoading={
                    run.isImported
                      ? loadingCat === run.category
                      : loadingRunId === run.run_id
                  }
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Detail panel — only for real runs, not imported */}
      {detailRunId && !detailRunId.startsWith('legacy_') && (
        <RunDetailPanel
          runId={detailRunId}
          onClose={() => setDetailRunId(null)}
          onViewLeads={handleViewLeads}
        />
      )}
    </Layout>
  )
}
