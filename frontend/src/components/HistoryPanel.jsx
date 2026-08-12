/**
 * HistoryPanel.jsx
 * ─────────────────
 * Unified history drawer showing:
 *   1. New generation runs (from generation_history collection) — each click = one run card
 *   2. Legacy category buckets (leads stored before history feature, no run_id)
 *
 * Tabs:
 *   [All] [Real Estate] [Construction] … [Legacy]
 *
 * "All" tab shows generation runs + legacy categories together.
 * Category tabs (Real Estate, Construction, …) show only runs for that category.
 * "Legacy" tab shows all legacy category buckets.
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  getHistory, getHistoryRun, getHistoryRunLeads,
  getLegacyCategories, getLegacyCategoryLeads,
  getSocialLeadsHistory, getSocialLeads,
} from '../services/api'

const POLL_INTERVAL_MS = 4000

/* ── helpers ───────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    }).format(new Date(iso))
  } catch { return iso?.slice(0, 16) ?? '—' }
}

function fmtDuration(secs) {
  if (secs == null) return null
  const s = Math.round(secs)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60), rem = s % 60
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`
}

/* ── StatusBadge ────────────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const map = {
    running:   { bg: 'bg-sky-50',     border: 'border-sky-200',     text: 'text-sky-700',     dot: 'bg-sky-400 animate-pulse', label: 'Running'   },
    completed: { bg: 'bg-emerald-50', border: 'border-emerald-200', text: 'text-emerald-700', dot: 'bg-emerald-400',           label: 'Completed' },
    failed:    { bg: 'bg-rose-50',    border: 'border-rose-200',    text: 'text-rose-700',    dot: 'bg-rose-400',              label: 'Failed'    },
    legacy:    { bg: 'bg-amber-50',   border: 'border-amber-200',   text: 'text-amber-700',   dot: 'bg-amber-400',             label: 'Legacy'    },
  }
  const s = map[status] ?? map.legacy
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                      border text-[11px] font-semibold ${s.bg} ${s.border} ${s.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${s.dot}`} />
      {s.label}
    </span>
  )
}

/* ── RunCard ─────────────────────────────────────────────────────────────────── */
function RunCard({ run, onViewDetails, onLoadData, loadingRunId }) {
  const duration = fmtDuration(run.duration_seconds)
  const isLoading = loadingRunId === run.run_id
  return (
    <div className="rounded-xl border border-slate-200 bg-white hover:border-indigo-200
                    hover:shadow-sm transition-all duration-150 overflow-hidden">
      <div className={`h-0.5 w-full ${
        run.status === 'completed' ? 'bg-emerald-400' :
        run.status === 'failed'    ? 'bg-rose-400'    : 'bg-sky-400'
      }`} />
      <div className="px-4 py-3.5">
        {/* category + status */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-sm font-bold text-slate-800 truncate">{run.category}</span>
          <StatusBadge status={run.status} />
        </div>
        {/* requested → generated */}
        <div className="flex items-center gap-3 mb-2 text-xs text-slate-600">
          <span><span className="font-semibold text-slate-800">{run.requested_count}</span> requested</span>
          <span className="text-slate-300">→</span>
          <span>
            <span className={`font-semibold ${
              run.status === 'completed' ? 'text-emerald-600' :
              run.status === 'failed'    ? 'text-rose-600'    : 'text-sky-600'
            }`}>{run.generated_count ?? '…'}</span> generated
          </span>
          {run.statistics?.duplicates > 0 && (
            <><span className="text-slate-300">·</span><span className="text-amber-600">{run.statistics.duplicates} dupes</span></>
          )}
        </div>
        {/* date + duration + run_id */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-2.5 text-[11px] text-slate-400">
          <span>{fmtDate(run.started_at)}</span>
          {duration && <><span className="text-slate-200">·</span><span>⏱ {duration}</span></>}
          {(run.state || run.district) && (
            <><span className="text-slate-200">·</span><span>📍 {[run.district, run.state].filter(Boolean).join(', ')}</span></>
          )}
          <span className="font-mono text-[10px] text-slate-300 block w-full mt-0.5">{run.run_id}</span>
        </div>
        {/* actions */}
        <div className="flex items-center gap-2 mt-1">
          <button onClick={() => onViewDetails(run.run_id)}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                       rounded-lg text-xs font-semibold border border-indigo-200
                       bg-indigo-50 text-indigo-700 hover:bg-indigo-100 hover:border-indigo-300
                       transition-colors focus:outline-none">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5
                   c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7
                   -4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            View Details
          </button>
          <button onClick={() => onLoadData(run)}
            disabled={run.status !== 'completed' || run.generated_count === 0 || isLoading}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                       rounded-lg text-xs font-semibold border border-emerald-200
                       bg-emerald-50 text-emerald-700 hover:bg-emerald-100
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {isLoading
              ? <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>Loading…</>
              : <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                  </svg>Load Data</>
            }
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── LegacyCard ──────────────────────────────────────────────────────────────── */
function LegacyCard({ entry, onLoadData, loadingCat }) {
  const isLoading = loadingCat === entry.category
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/40 hover:border-amber-300
                    hover:shadow-sm transition-all duration-150 overflow-hidden">
      <div className="h-0.5 w-full bg-amber-400" />
      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-sm font-bold text-slate-800 truncate">{entry.category}</span>
          <StatusBadge status="legacy" />
        </div>
        <div className="flex items-center gap-3 mb-2 text-xs text-slate-600">
          <span><span className="font-semibold text-slate-800">{entry.total_leads}</span> total leads</span>
          {entry.legacy_leads !== entry.total_leads && (
            <><span className="text-slate-300">·</span>
              <span className="text-amber-600">{entry.legacy_leads} without run ID</span></>
          )}
        </div>
        {entry.newest_lead_at && (
          <p className="text-[11px] text-slate-400 mb-2.5">Last saved: {fmtDate(entry.newest_lead_at)}</p>
        )}
        <button onClick={() => onLoadData(entry)}
          disabled={isLoading}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                     rounded-lg text-xs font-semibold border border-amber-300
                     bg-amber-100 text-amber-800 hover:bg-amber-200
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isLoading
            ? <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>Loading {entry.total_leads} leads…</>
            : <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                </svg>Load {entry.total_leads} Leads into Table</>
          }
        </button>
      </div>
    </div>
  )
}

/* ── SocialCard ──────────────────────────────────────────────────────────────── */
const PLT_ICONS = {
  linkedin: '💼', x: '𝕏', whatsapp: '💬', facebook: '👥', website: '🌐', other: '🔗',
}
const PLT_COLORS = {
  linkedin: 'border-sky-200 bg-sky-50/40 hover:border-sky-300',
  x:        'border-slate-200 bg-slate-50/40 hover:border-slate-300',
  whatsapp: 'border-green-200 bg-green-50/40 hover:border-green-300',
  facebook: 'border-blue-200 bg-blue-50/40 hover:border-blue-300',
  website:  'border-violet-200 bg-violet-50/40 hover:border-violet-300',
  other:    'border-slate-200 bg-slate-50/40 hover:border-slate-300',
}
const PLT_BAR = {
  linkedin: 'bg-sky-400', x: 'bg-slate-500', whatsapp: 'bg-green-500',
  facebook: 'bg-blue-500', website: 'bg-violet-500', other: 'bg-slate-400',
}

function SocialCard({ group, onViewLeads, loadingKey }) {
  const key = `${group.platform}|${group.form_id}|${group.campaign_id || ''}`
  const isLoading = loadingKey === key
  const plt = group.platform || 'other'
  return (
    <div className={`rounded-xl border hover:shadow-sm transition-all duration-150 overflow-hidden
                     ${PLT_COLORS[plt] ?? PLT_COLORS.other}`}>
      <div className={`h-0.5 w-full ${PLT_BAR[plt] ?? PLT_BAR.other}`} />
      <div className="px-4 py-3.5">
        {/* platform + count */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-base flex-shrink-0">{PLT_ICONS[plt] ?? '🔗'}</span>
            <span className="text-sm font-bold text-slate-800 truncate capitalize">{plt}</span>
          </div>
          <span className="flex-shrink-0 inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                           bg-white/80 border border-slate-200 text-[11px] font-bold text-slate-700">
            {group.count} lead{group.count !== 1 ? 's' : ''}
          </span>
        </div>
        {/* form + campaign */}
        <p className="text-xs font-semibold text-slate-700 truncate mb-0.5">{group.form_name || group.form_id}</p>
        {group.campaign_name && (
          <p className="text-[11px] text-slate-400 truncate mb-1">📣 {group.campaign_name}</p>
        )}
        <p className="text-[11px] text-slate-400 mb-0.5">🏷 {group.category || '—'}</p>
        {/* dates */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-slate-400 mb-3 mt-1">
          {group.first_submission && <span>First: {fmtDate(group.first_submission)}</span>}
          {group.last_submission  && <span>Latest: {fmtDate(group.last_submission)}</span>}
        </div>
        {/* action */}
        <button onClick={() => onViewLeads(group, key)}
          disabled={isLoading}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5
                     rounded-lg text-xs font-semibold border border-indigo-200
                     bg-indigo-50 text-indigo-700 hover:bg-indigo-100 hover:border-indigo-300
                     disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {isLoading
            ? <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>Loading {group.count} leads…</>
            : <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                </svg>Load {group.count} Leads</>
          }
        </button>
      </div>
    </div>
  )
}

/* ── LogEntry ───────────────────────────────────────────────────────────────── */
function LogEntry({ entry }) {
  const colors = {
    INFO: 'text-slate-500', SEARCH: 'text-sky-600', FILTER: 'text-violet-600',
    SCRAPE: 'text-amber-600', EXTRACT: 'text-indigo-600', VALIDATION: 'text-teal-600',
    DATABASE: 'text-blue-600', COMPLETE: 'text-emerald-600', ERROR: 'text-rose-600',
  }
  return (
    <div className="flex items-start gap-2 py-1 text-[11px] font-mono">
      <span className="text-slate-400 flex-shrink-0 w-[56px]">{entry.timestamp}</span>
      <span className={`font-bold flex-shrink-0 w-[72px] ${colors[entry.level] ?? 'text-slate-500'}`}>{entry.level}</span>
      <span className="text-slate-600 leading-snug break-all">{entry.message}</span>
    </div>
  )
}

function StatRow({ label, value, highlight }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-bold ${highlight ? 'text-indigo-600' : 'text-slate-700'}`}>{value ?? '—'}</span>
    </div>
  )
}

/* ── RunDetailPanel ──────────────────────────────────────────────────────────── */
function RunDetailPanel({ runId, onClose, onLoadIntoTable }) {
  const [run, setRun]               = useState(null)
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState(null)
  const [loadingLeads, setLoadingLeads] = useState(false)
  const logsEndRef = useRef(null)
  const pollRef    = useRef(null)

  const fetchRun = useCallback(async () => {
    try {
      const data = await getHistoryRun(runId)
      setRun(data.run)
      setError(null)
      if (data.run?.status === 'running') {
        pollRef.current = setTimeout(fetchRun, POLL_INTERVAL_MS)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [runId])

  useEffect(() => { fetchRun(); return () => clearTimeout(pollRef.current) }, [fetchRun])
  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [run?.logs?.length])

  const handleLoad = async () => {
    setLoadingLeads(true)
    try {
      const data = await getHistoryRunLeads(runId, { per_page: 500 })
      onLoadIntoTable(data.leads ?? [], run.category, run.run_id)
    } catch (err) { alert(`Failed to load leads: ${err.message}`) }
    finally { setLoadingLeads(false) }
  }

  const stats = run?.statistics ?? {}

  return (
    <div className="absolute inset-0 bg-white z-10 flex flex-col overflow-hidden"
         style={{ animation: 'slideInRight 0.18s ease both' }}>
      {/* header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 flex-shrink-0">
        <button onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-lg
                     text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/>
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-bold text-slate-800 truncate">{run?.category ?? 'Generation Run'}</h3>
          <p className="text-[11px] text-slate-400 font-mono">{runId}</p>
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
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5 scrollbar-thin">
          {/* Run info */}
          <section>
            <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Run Details</h4>
            <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
              <StatRow label="Run ID"       value={<span className="font-mono text-[10px]">{run.run_id}</span>} />
              <StatRow label="Category"     value={run.category} />
              <StatRow label="Search Query" value={run.search_query || '—'} />
              <StatRow label="Location"     value={[run.district, run.state].filter(Boolean).join(', ') || '—'} />
              <StatRow label="Requested"    value={run.requested_count} />
              <StatRow label="Generated"    value={run.generated_count} highlight />
              <StatRow label="Started"      value={fmtDate(run.started_at)} />
              <StatRow label="Completed"    value={fmtDate(run.completed_at || run.failed_at)} />
              <StatRow label="Duration"     value={fmtDuration(run.duration_seconds)} />
            </div>
          </section>

          {/* Statistics */}
          {Object.keys(stats).length > 0 && (
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Statistics</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
                {stats.companies_discovered != null && <StatRow label="Companies discovered" value={stats.companies_discovered} />}
                {stats.companies_processed  != null && <StatRow label="Companies processed"  value={stats.companies_processed} />}
                {stats.leads_generated      != null && <StatRow label="Leads generated"       value={stats.leads_generated} highlight />}
                {stats.duplicates           != null && <StatRow label="Duplicates skipped"    value={stats.duplicates} />}
                {stats.with_email           != null && <StatRow label="With email"            value={stats.with_email} />}
                {stats.with_phone           != null && <StatRow label="With phone"            value={stats.with_phone} />}
                {stats.elapsed_seconds      != null && <StatRow label="Duration"              value={fmtDuration(stats.elapsed_seconds)} />}
              </div>
            </section>
          )}

          {/* Logs */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest">
                Logs <span className="text-slate-300 font-normal">({run.logs?.length ?? 0})</span>
              </h4>
              {run.status === 'running' && (
                <span className="inline-flex items-center gap-1 text-[10px] text-sky-600 font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />Live
                </span>
              )}
            </div>
            <div className="rounded-xl border border-slate-100 bg-slate-900/[0.03] px-3 py-2
                            max-h-[280px] overflow-y-auto scrollbar-thin divide-y divide-slate-100/60">
              {(run.logs ?? []).length === 0
                ? <p className="text-[11px] text-slate-400 italic py-3">No logs yet.</p>
                : (run.logs ?? []).map((e, i) => <LogEntry key={i} entry={e} />)
              }
              <div ref={logsEndRef} />
            </div>
          </section>

          {run.error_message && (
            <section>
              <h4 className="text-[11px] font-bold text-rose-400 uppercase tracking-widest mb-2">Error</h4>
              <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
                {run.error_message}
              </div>
            </section>
          )}
        </div>
      )}

      {/* footer */}
      {!loading && run && (
        <div className="flex-shrink-0 px-5 py-4 border-t border-slate-200 bg-white">
          <button onClick={handleLoad}
            disabled={run.status !== 'completed' || run.generated_count === 0 || loadingLeads}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-3
                       rounded-xl text-sm font-semibold text-white bg-indigo-600
                       hover:bg-indigo-700 shadow-sm disabled:opacity-50 disabled:cursor-not-allowed
                       transition-colors">
            {loadingLeads
              ? <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>Loading {run.generated_count} leads…</>
              : <><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                  </svg>Load {run.generated_count} Leads into Table</>
            }
          </button>
          {run.status !== 'completed' && (
            <p className="text-center text-[11px] text-slate-400 mt-2">
              {run.status === 'running' ? 'Generation still running…' : 'Run failed — no leads to load.'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   MAIN PANEL
   ══════════════════════════════════════════════════════════════════════════════ */
export default function HistoryPanel({ onClose, onLoadLeads }) {
  /* ── state ─────────────────────────────────────────────────────────────── */
  const [runs,          setRuns]         = useState([])
  const [legacyCats,    setLegacyCats]   = useState([])   // [{category, total_leads, …}]
  const [allRunCats,    setAllRunCats]   = useState([])   // unique category names from runs
  const [socialGroups,  setSocialGroups] = useState([])   // [{platform, form_name, campaign_name, count, …}]
  const [activeCat,     setActiveCat]   = useState('All')
  const [loading,       setLoading]     = useState(true)
  const [loadError,     setLoadError]   = useState(null)
  const [searchQuery,   setSearchQuery] = useState('')
  const [detailRunId,   setDetailRunId] = useState(null)
  const [loadingRunId,  setLoadingRunId]  = useState(null)  // for Run "Load Data"
  const [loadingCat,    setLoadingCat]    = useState(null)  // for Legacy "Load"
  const [loadingSocKey, setLoadingSocKey] = useState(null)  // for Social "Load"
  const pollRef = useRef(null)

  /* ── fetch runs + legacy in parallel ─────────────────────────────────── */
  const fetchAll = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const [runsData, legacyData, socialData] = await Promise.all([
        getHistory({ per_page: 200 }).catch(() => ({ runs: [], categories: [] })),
        getLegacyCategories().catch(() => ({ legacy_categories: [] })),
        getSocialLeadsHistory().catch(() => ({ groups: [], total: 0 })),
      ])

      const fetchedRuns = runsData.runs ?? []
      setRuns(fetchedRuns)
      setAllRunCats(runsData.categories ?? [])
      setLegacyCats(legacyData.legacy_categories ?? [])
      setSocialGroups(socialData.groups ?? [])
      setLoadError(null)

      // Keep polling while any run is still running
      if (fetchedRuns.some(r => r.status === 'running')) {
        pollRef.current = setTimeout(() => fetchAll(true), POLL_INTERVAL_MS)
      }
    } catch (err) {
      setLoadError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    clearTimeout(pollRef.current)
    fetchAll()
    return () => clearTimeout(pollRef.current)
  }, [fetchAll])

  /* ── Load Data for a run card (without opening detail) ───────────────── */
  const handleLoadRun = useCallback(async (run) => {
    setLoadingRunId(run.run_id)
    try {
      const data = await getHistoryRunLeads(run.run_id, { per_page: 500 })
      onLoadLeads(data.leads ?? [], run.category, run.run_id)
      onClose()
    } catch (err) { alert(`Failed to load leads: ${err.message}`) }
    finally { setLoadingRunId(null) }
  }, [onLoadLeads, onClose])

  /* ── Load Data for a legacy category card ─────────────────────────────── */
  const handleLoadLegacy = useCallback(async (entry) => {
    setLoadingCat(entry.category)
    try {
      const data = await getLegacyCategoryLeads(entry.category, { per_page: 500 })
      onLoadLeads(data.leads ?? [], entry.category, null)
      onClose()
    } catch (err) { alert(`Failed to load legacy leads: ${err.message}`) }
    finally { setLoadingCat(null) }
  }, [onLoadLeads, onClose])

  /* ── Load Data for a social leads group card ───────────────────────────── */
  const handleLoadSocialGroup = useCallback(async (group, key) => {
    setLoadingSocKey(key)
    try {
      const params = {
        platform:    group.platform,
        form_id:     group.form_id,
        per_page:    500,
      }
      if (group.campaign_id) params.campaign_id = group.campaign_id
      const data = await getSocialLeads(params)
      const label = `${group.form_name} · ${group.campaign_name || group.platform}`
      onLoadLeads(data.leads ?? [], label, null)
      onClose()
    } catch (err) { alert(`Failed to load social leads: ${err.message}`) }
    finally { setLoadingSocKey(null) }
  }, [onLoadLeads, onClose])

  /* ── Load from detail panel ──────────────────────────────────────────── */
  const handleLoadFromDetail = useCallback((leads, category, runId) => {
    onLoadLeads(leads, category, runId)
    onClose()
  }, [onLoadLeads, onClose])

  /* ── Tab categories ──────────────────────────────────────────────────── */
  // [All, ...run categories, Legacy (if any legacy exist), Social Leads (if any social exist)]
  const tabs = [
    'All',
    ...allRunCats,
    ...(legacyCats.length > 0 ? ['Legacy'] : []),
    ...(socialGroups.length > 0 ? ['Social Leads'] : []),
  ]

  /* ── Compute what to show based on active tab ────────────────────────── */
  const visibleRuns = activeCat === 'All'
    ? runs
    : activeCat === 'Legacy' || activeCat === 'Social Leads'
      ? []
      : runs.filter(r => r.category?.toLowerCase() === activeCat.toLowerCase())

  const visibleLegacy = activeCat === 'All' || activeCat === 'Legacy'
    ? legacyCats
    : []

  const visibleSocial = activeCat === 'All' || activeCat === 'Social Leads'
    ? socialGroups
    : []

  /* ── Search filter across both ───────────────────────────────────────── */
  const q = searchQuery.trim().toLowerCase()
  const filteredRuns = q
    ? visibleRuns.filter(r =>
        r.category?.toLowerCase().includes(q) ||
        r.run_id?.toLowerCase().includes(q) ||
        r.search_query?.toLowerCase().includes(q) ||
        r.state?.toLowerCase().includes(q) ||
        r.district?.toLowerCase().includes(q)
      )
    : visibleRuns

  const filteredLegacy = q
    ? visibleLegacy.filter(e => e.category?.toLowerCase().includes(q))
    : visibleLegacy

  const filteredSocial = q
    ? visibleSocial.filter(g =>
        g.form_name?.toLowerCase().includes(q) ||
        g.campaign_name?.toLowerCase().includes(q) ||
        g.platform?.toLowerCase().includes(q) ||
        g.category?.toLowerCase().includes(q)
      )
    : visibleSocial

  const totalVisible = filteredRuns.length + filteredLegacy.length + filteredSocial.length
  const hasRunning   = runs.some(r => r.status === 'running')

  /* ── Tab badge count ─────────────────────────────────────────────────── */
  const tabCount = (tab) => {
    if (tab === 'All') return runs.length + legacyCats.length + socialGroups.length
    if (tab === 'Legacy') return legacyCats.length
    if (tab === 'Social Leads') return socialGroups.length
    return runs.filter(r => r.category?.toLowerCase() === tab.toLowerCase()).length
  }

  /* ── backdrop ─────────────────────────────────────────────────────────── */
  const handleBackdrop = (e) => { if (e.target === e.currentTarget) onClose() }

  /* ── render ───────────────────────────────────────────────────────────── */
  return (
    <div className="fixed inset-0 z-50 flex justify-end"
         style={{ background: 'rgba(15,23,42,0.5)' }}
         onClick={handleBackdrop}>
      <div className="relative w-full max-w-[500px] h-full bg-white shadow-2xl
                      flex flex-col overflow-hidden"
           style={{ animation: 'slideInRight 0.22s cubic-bezier(0.25,0.46,0.45,0.94) both' }}
           onClick={e => e.stopPropagation()}>

        {/* ── HEADER ──────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-5 py-4
                        border-b border-slate-200 bg-white flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center
                            justify-center shadow-sm flex-shrink-0">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">Lead History</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {loading ? 'Loading…' : (
                  <>
                    {runs.length} run{runs.length !== 1 ? 's' : ''}
                    {legacyCats.length > 0 && ` · ${legacyCats.reduce((s, c) => s + c.total_leads, 0)} legacy`}
                    {socialGroups.length > 0 && ` · ${socialGroups.reduce((s, g) => s + g.count, 0)} social`}
                  </>
                )}
                {hasRunning && (
                  <span className="ml-2 inline-flex items-center gap-1 text-sky-500 font-semibold">
                    <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />live
                  </span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={() => fetchAll()} disabled={loading} title="Refresh"
              className="w-8 h-8 flex items-center justify-center rounded-lg
                         text-slate-500 hover:bg-slate-100 hover:text-indigo-600
                         transition-colors disabled:opacity-50">
              <svg className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`}
                   fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581
                     m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
            </button>
            <button onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-lg
                         text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>

        {/* ── TABS ────────────────────────────────────────────────────── */}
        {!loading && tabs.length > 1 && (
          <div className="px-4 pt-3 pb-0 flex-shrink-0">
            <div className="flex gap-1.5 overflow-x-auto scrollbar-hide pb-3">
              {tabs.map(tab => {
                const cnt   = tabCount(tab)
                const active = activeCat === tab
                return (
                  <button key={tab}
                    onClick={() => { setActiveCat(tab); setSearchQuery('') }}
                    className={`flex-shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                      text-xs font-semibold transition-all whitespace-nowrap
                      focus:outline-none focus:ring-2 focus:ring-indigo-400
                      ${active
                        ? tab === 'Legacy'
                          ? 'bg-amber-500 text-white shadow-sm'
                          : tab === 'Social Leads'
                            ? 'bg-violet-600 text-white shadow-sm'
                            : 'bg-indigo-600 text-white shadow-sm'
                        : tab === 'Legacy'
                          ? 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100'
                          : tab === 'Social Leads'
                            ? 'bg-violet-50 text-violet-700 border border-violet-200 hover:bg-violet-100'
                            : 'bg-slate-100 text-slate-600 hover:bg-indigo-50 hover:text-indigo-700'
                      }`}>
                    {tab}
                    <span className={`inline-flex items-center justify-center rounded-full
                                      px-1.5 min-w-[18px] h-[18px] text-[10px] font-bold
                                      ${active ? 'bg-white/25 text-white' : 'bg-slate-300/70 text-slate-600'}`}>
                      {cnt}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* ── SEARCH ──────────────────────────────────────────────────── */}
        {!loading && (runs.length + legacyCats.length + socialGroups.length) > 0 && (
          <div className="px-4 py-2.5 border-b border-slate-100 flex-shrink-0">
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
              </div>
              <input type="text" value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search by category, location, run ID…"
                className="w-full rounded-lg border border-slate-200 bg-white
                           pl-8 pr-8 py-2 text-xs text-slate-800 placeholder-slate-400
                           focus:outline-none focus:ring-2 focus:ring-indigo-400 transition-all" />
              {searchQuery && (
                <button onClick={() => setSearchQuery('')}
                  className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-600">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              )}
            </div>
          </div>
        )}

        {/* ── BODY ────────────────────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto relative">

          {/* Spinner */}
          {loading && (
            <div className="flex flex-col items-center justify-center py-20 gap-3">
              <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
              <p className="text-sm text-slate-500">Loading history…</p>
            </div>
          )}

          {/* Error */}
          {loadError && !loading && (
            <div className="m-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
              {loadError}
            </div>
          )}

          {/* Empty state */}
          {!loading && !loadError && runs.length === 0 && legacyCats.length === 0 && socialGroups.length === 0 && (
            <div className="flex flex-col items-center justify-center gap-4 py-20 px-8">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center">
                <svg className="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-slate-700">No history yet</p>
                <p className="text-xs text-slate-400 mt-1">Generate leads — every run appears here automatically.</p>
              </div>
            </div>
          )}

          {/* Main list */}
          {!loading && !loadError && totalVisible > 0 && (
            <div className="px-4 py-3 space-y-3">

              {/* Generation runs */}
              {filteredRuns.length > 0 && (
                <>
                  {(activeCat === 'All' && filteredLegacy.length > 0) && (
                    <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest pt-1 pb-0.5">
                      Generation Runs
                    </p>
                  )}
                  {filteredRuns.map(run => (
                    <RunCard key={run.run_id} run={run}
                      onViewDetails={id => setDetailRunId(id)}
                      onLoadData={handleLoadRun}
                      loadingRunId={loadingRunId} />
                  ))}
                </>
              )}

              {/* Legacy categories */}
              {filteredLegacy.length > 0 && (
                <>
                  {(activeCat === 'All' && filteredRuns.length > 0) && (
                    <div className="flex items-center gap-3 pt-2">
                      <div className="flex-1 h-px bg-amber-200" />
                      <span className="text-[11px] font-bold text-amber-500 uppercase tracking-widest whitespace-nowrap">
                        Legacy Data
                      </span>
                      <div className="flex-1 h-px bg-amber-200" />
                    </div>
                  )}
                  {activeCat === 'Legacy' && (
                    <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-center">
                      These leads were stored before the generation history feature was added.
                      They are not linked to a specific run.
                    </p>
                  )}
                  {filteredLegacy.map(entry => (
                    <LegacyCard key={entry.category} entry={entry}
                      onLoadData={handleLoadLegacy}
                      loadingCat={loadingCat} />
                  ))}
                </>
              )}

              {/* Social Leads groups */}
              {filteredSocial.length > 0 && (
                <>
                  {(activeCat === 'All' && (filteredRuns.length > 0 || filteredLegacy.length > 0)) && (
                    <div className="flex items-center gap-3 pt-2">
                      <div className="flex-1 h-px bg-violet-200" />
                      <span className="text-[11px] font-bold text-violet-500 uppercase tracking-widest whitespace-nowrap">
                        Social Leads
                      </span>
                      <div className="flex-1 h-px bg-violet-200" />
                    </div>
                  )}
                  {activeCat === 'Social Leads' && (
                    <div className="flex items-center justify-between mb-1">
                      <p className="text-[11px] text-violet-600 bg-violet-50 border border-violet-200 rounded-lg px-3 py-2 flex-1 text-center">
                        Form submissions grouped by platform · form · campaign.
                        Click a card to load those leads into the main table.
                      </p>
                      <a href="/social-leads"
                        className="ml-2 flex-shrink-0 text-[11px] text-violet-600 hover:text-violet-800
                                   font-semibold underline underline-offset-2">
                        Open Dashboard →
                      </a>
                    </div>
                  )}
                  {filteredSocial.map((group, i) => (
                    <SocialCard
                      key={`${group.platform}-${group.form_id}-${group.campaign_id || i}`}
                      group={group}
                      onViewLeads={handleLoadSocialGroup}
                      loadingKey={loadingSocKey}
                    />
                  ))}
                </>
              )}

              {/* Footer note */}
              <p className="text-center text-[11px] text-slate-300 pb-2 pt-1">
                {totalVisible} item{totalVisible !== 1 ? 's' : ''} shown
                {searchQuery && ` · matching "${searchQuery}"`}
              </p>
            </div>
          )}

          {/* No search results */}
          {!loading && !loadError && (runs.length + legacyCats.length + socialGroups.length) > 0 && totalVisible === 0 && (
            <div className="flex flex-col items-center py-16 gap-2 px-8">
              <p className="text-sm font-semibold text-slate-600">No results match "{searchQuery}"</p>
              <button onClick={() => setSearchQuery('')}
                className="text-xs text-indigo-500 hover:underline">Clear search</button>
            </div>
          )}

          {/* Detail panel overlay */}
          {detailRunId && (
            <RunDetailPanel
              runId={detailRunId}
              onClose={() => setDetailRunId(null)}
              onLoadIntoTable={handleLoadFromDetail} />
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0.8; }
          to   { transform: translateX(0);    opacity: 1;   }
        }
      `}</style>
    </div>
  )
}
