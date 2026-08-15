/**
 * HistoryPanel.jsx — Lead History slide-in drawer
 * Features:
 *  - Shows ALL generation runs (generation_history collection)
 *  - Category DROPDOWN  (All Categories / Today's Leads / every distinct category)
 *  - Source chips: All · Maps · Reddit
 *  - Full-text search
 *  - Legacy data section
 *  - Social Leads section
 *  - RunDetailPanel slide-in with logs + stats
 *  - Download All → Excel
 *  - Auto-polls while any run is "running"
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  getHistory, getHistoryRun, getHistoryRunLeads,
  getLegacyCategories, getLegacyCategoryLeads,
  getSocialLeadsHistory, getSocialLeads,
  buildAllCategoriesExcelUrl,
} from '../services/api'

const POLL_INTERVAL_MS = 5000

/* ─── tiny helpers ──────────────────────────────────────────────────────── */
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
  return s < 60 ? `${s}s` : `${Math.floor(s/60)}m ${s%60>0?s%60+'s':''}`
}
function todayStr() { return new Date().toISOString().slice(0, 10) }
function isToday(iso) { return !!iso && iso.slice(0, 10) === todayStr() }

/* ─── StatusBadge ───────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const m = {
    running:   'bg-sky-50 border-sky-200 text-sky-700',
    completed: 'bg-emerald-50 border-emerald-200 text-emerald-700',
    failed:    'bg-rose-50 border-rose-200 text-rose-700',
    legacy:    'bg-amber-50 border-amber-200 text-amber-700',
  }
  const dot = {
    running: 'bg-sky-400 animate-pulse', completed: 'bg-emerald-400',
    failed: 'bg-rose-400', legacy: 'bg-amber-400',
  }
  const label = { running:'Running', completed:'Completed', failed:'Failed', legacy:'Legacy' }
  const k = m[status] ? status : 'legacy'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold ${m[k]}`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dot[k]}`} />
      {label[k]}
    </span>
  )
}

/* ─── RunCard ───────────────────────────────────────────────────────────── */
function RunCard({ run, onViewDetails, onLoadData, loadingRunId }) {
  const busy     = loadingRunId === run.run_id
  const isReddit = run.source === 'reddit'
  const today    = isToday(run.started_at)
  return (
    <div className={`rounded-xl border overflow-hidden hover:shadow-sm transition-all
      ${isReddit ? 'border-orange-200 bg-white hover:border-orange-300'
                 : 'border-slate-200 bg-white hover:border-indigo-200'}`}>
      {/* colour top bar */}
      <div className={`h-0.5 w-full ${
        run.status==='completed' ? (isReddit?'bg-orange-400':'bg-emerald-400')
        : run.status==='failed'  ? 'bg-rose-400' : 'bg-sky-400'}`} />

      <div className="px-4 py-3.5">
        {/* header row */}
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex flex-wrap items-center gap-1.5 min-w-0">
            {isReddit && (
              <span className="flex-shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full
                bg-orange-50 border border-orange-200 text-orange-700 text-[10px] font-bold">
                <svg className="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M10 0C4.478 0 0 4.478 0 10s4.478 10 10 10 10-4.478 10-10S15.522 0 10 0zm5.935 11.35c.026.19.04.382.04.577 0 2.952-3.44 5.347-7.685 5.347-4.244 0-7.684-2.395-7.684-5.347 0-.195.014-.387.04-.577a1.384 1.384 0 01-.576-1.126 1.39 1.39 0 012.39-.961c1.18-.854 2.814-1.399 4.631-1.455l.786-3.703a.278.278 0 01.328-.215l2.607.547a.972.972 0 01.946-.754.972.972 0 010 1.943.972.972 0 01-.972-.972l-2.33-.489-.71 3.34c1.8.063 3.42.608 4.59 1.457a1.39 1.39 0 012.39.961 1.384 1.384 0 01-.79 1.227zM6.875 10.417a.972.972 0 010 1.943.972.972 0 010-1.943zm6.25 0a.972.972 0 010 1.943.972.972 0 010-1.943zm-4.948 3.75c.43.43 1.128.64 2.113.64.986 0 1.684-.21 2.114-.64a.278.278 0 10-.394-.394c-.332.332-.895.59-1.72.59-.824 0-1.387-.258-1.72-.59a.278.278 0 10-.393.394z"/>
                </svg>
                Reddit
              </span>
            )}
            {today && (
              <span className="flex-shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-full
                bg-amber-50 border border-amber-200 text-amber-700 text-[10px] font-bold">
                Today
              </span>
            )}
            <span className="text-sm font-bold text-slate-800 truncate">{run.category}</span>
          </div>
          <StatusBadge status={run.status} />
        </div>

        {/* stats */}
        <div className="flex items-center gap-3 mb-2 text-xs text-slate-600">
          <span><strong className="text-slate-800">{run.requested_count}</strong> requested</span>
          <span className="text-slate-300">→</span>
          <span>
            <strong className={run.status==='completed'?(isReddit?'text-orange-600':'text-emerald-600'):run.status==='failed'?'text-rose-600':'text-sky-600'}>
              {run.generated_count ?? '…'}
            </strong> generated
          </span>
          {(run.statistics?.duplicates ?? 0) > 0 && (
            <><span className="text-slate-300">·</span>
              <span className="text-amber-600">{run.statistics.duplicates} dupes</span></>
          )}
        </div>

        {/* meta */}
        <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-400 mb-3">
          <span>{fmtDate(run.started_at)}</span>
          {fmtDur(run.duration_seconds) && <span>⏱ {fmtDur(run.duration_seconds)}</span>}
          {(run.state||run.district) && <span>📍 {[run.district,run.state].filter(Boolean).join(', ')}</span>}
          <span className="font-mono text-[10px] text-slate-300 w-full mt-0.5">{run.run_id}</span>
        </div>

        {/* action buttons */}
        <div className="flex gap-2">
          <button onClick={() => onViewDetails(run.run_id)}
            className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
              rounded-lg text-xs font-semibold border transition-colors focus:outline-none
              ${isReddit
                ? 'border-orange-200 bg-orange-50 text-orange-700 hover:bg-orange-100'
                : 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'}`}>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5
                   c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7
                   -4.477 0-8.268-2.943-9.542-7z"/>
            </svg>
            Details
          </button>
          <button
            onClick={() => onLoadData(run)}
            disabled={run.status !== 'completed' || !run.generated_count || busy}
            className="flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-1.5
              rounded-lg text-xs font-semibold border border-emerald-200
              bg-emerald-50 text-emerald-700 hover:bg-emerald-100
              disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
            {busy ? (
              <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>Loading…</>
            ) : (
              <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                </svg>Load Data</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ─── LegacyCard ────────────────────────────────────────────────────────── */
function LegacyCard({ entry, onLoadData, loadingCat }) {
  const busy = loadingCat === entry.category
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/40 hover:border-amber-300 hover:shadow-sm transition-all overflow-hidden">
      <div className="h-0.5 w-full bg-amber-400" />
      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-2 mb-2">
          <span className="text-sm font-bold text-slate-800 truncate">{entry.category}</span>
          <StatusBadge status="legacy" />
        </div>
        <div className="flex gap-3 text-xs text-slate-600 mb-1.5">
          <span><strong className="text-slate-800">{entry.total_leads}</strong> leads</span>
          {entry.legacy_leads !== entry.total_leads && (
            <span className="text-amber-600">{entry.legacy_leads} without run ID</span>
          )}
        </div>
        {entry.newest_lead_at && (
          <p className="text-[11px] text-slate-400 mb-2.5">Last saved: {fmtDate(entry.newest_lead_at)}</p>
        )}
        <button onClick={() => onLoadData(entry)} disabled={busy}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg
            text-xs font-semibold border border-amber-300 bg-amber-100 text-amber-800
            hover:bg-amber-200 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {busy ? (
            <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>Loading…</>
          ) : (
            <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
              </svg>Load {entry.total_leads} Leads into Table</>
          )}
        </button>
      </div>
    </div>
  )
}

/* ─── SocialCard ────────────────────────────────────────────────────────── */
const PLT_ICON  = { linkedin:'💼', x:'𝕏', whatsapp:'💬', facebook:'👥', website:'🌐', other:'🔗' }
const PLT_STYLE = { linkedin:'border-sky-200 bg-sky-50/40', x:'border-slate-200 bg-slate-50/40', whatsapp:'border-green-200 bg-green-50/40', facebook:'border-blue-200 bg-blue-50/40', website:'border-violet-200 bg-violet-50/40', other:'border-slate-200 bg-slate-50/40' }
const PLT_BAR   = { linkedin:'bg-sky-400', x:'bg-slate-500', whatsapp:'bg-green-500', facebook:'bg-blue-500', website:'bg-violet-500', other:'bg-slate-400' }

function SocialCard({ group, onViewLeads, loadingKey }) {
  const key  = `${group.platform}|${group.form_id}|${group.campaign_id||''}`
  const busy = loadingKey === key
  const plt  = group.platform || 'other'
  return (
    <div className={`rounded-xl border hover:shadow-sm transition-all overflow-hidden ${PLT_STYLE[plt]??PLT_STYLE.other}`}>
      <div className={`h-0.5 w-full ${PLT_BAR[plt]??PLT_BAR.other}`} />
      <div className="px-4 py-3.5">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-base">{PLT_ICON[plt]??'🔗'}</span>
            <span className="text-sm font-bold text-slate-800 truncate capitalize">{plt}</span>
          </div>
          <span className="text-[11px] font-bold text-slate-700 flex-shrink-0 px-2 py-0.5 rounded-full bg-white/80 border border-slate-200">
            {group.count} lead{group.count!==1?'s':''}
          </span>
        </div>
        <p className="text-xs font-semibold text-slate-700 truncate mb-0.5">{group.form_name||group.form_id}</p>
        {group.campaign_name && <p className="text-[11px] text-slate-400 truncate mb-1">📣 {group.campaign_name}</p>}
        <p className="text-[11px] text-slate-400 mb-0.5">🏷 {group.category||'—'}</p>
        <div className="flex flex-wrap gap-x-3 text-[10px] text-slate-400 mb-3">
          {group.first_submission && <span>First: {fmtDate(group.first_submission)}</span>}
          {group.last_submission  && <span>Latest: {fmtDate(group.last_submission)}</span>}
        </div>
        <button onClick={() => onViewLeads(group, key)} disabled={busy}
          className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg
            text-xs font-semibold border border-indigo-200 bg-indigo-50 text-indigo-700
            hover:bg-indigo-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {busy ? (
            <><svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>Loading…</>
          ) : (
            <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
              </svg>Load Leads</>
          )}
        </button>
      </div>
    </div>
  )
}

/* ─── LogEntry / StatRow ─────────────────────────────────────────────────── */
function LogEntry({ entry }) {
  const C = { INFO:'text-slate-500', SEARCH:'text-sky-600', FILTER:'text-violet-600', SCRAPE:'text-amber-600', EXTRACT:'text-indigo-600', VALIDATION:'text-teal-600', DATABASE:'text-blue-600', COMPLETE:'text-emerald-600', ERROR:'text-rose-600' }
  return (
    <div className="flex items-start gap-2 py-1 text-[11px] font-mono">
      <span className="text-slate-400 flex-shrink-0 w-14">{entry.timestamp}</span>
      <span className={`font-bold flex-shrink-0 w-[72px] ${C[entry.level]??'text-slate-500'}`}>{entry.level}</span>
      <span className="text-slate-600 leading-snug break-all">{entry.message}</span>
    </div>
  )
}
function StatRow({ label, value, highlight }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`text-xs font-bold ${highlight?'text-indigo-600':'text-slate-700'}`}>{value??'—'}</span>
    </div>
  )
}

/* ─── RunDetailPanel ─────────────────────────────────────────────────────── */
function RunDetailPanel({ runId, onClose, onLoadIntoTable }) {
  const [run, setRun]         = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [busy, setBusy]       = useState(false)
  const logsEndRef = useRef(null)
  const pollRef    = useRef(null)

  const fetchRun = useCallback(async () => {
    try {
      const d = await getHistoryRun(runId)
      setRun(d.run); setError(null)
      if (d.run?.status === 'running') pollRef.current = setTimeout(fetchRun, POLL_INTERVAL_MS)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [runId])

  useEffect(() => { fetchRun(); return () => clearTimeout(pollRef.current) }, [fetchRun])
  useEffect(() => { logsEndRef.current?.scrollIntoView({ behavior:'smooth' }) }, [run?.logs?.length])

  const handleLoad = async () => {
    setBusy(true)
    try {
      const d = await getHistoryRunLeads(runId, { per_page: 500 })
      onLoadIntoTable(d.leads ?? [], run.category, run.run_id)
    } catch (e) { alert(`Failed: ${e.message}`) }
    finally { setBusy(false) }
  }

  const stats = run?.statistics ?? {}
  return (
    <div className="absolute inset-0 bg-white z-10 flex flex-col overflow-hidden"
         style={{ animation: 'slideInRight 0.18s ease both' }}>
      {/* header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 flex-shrink-0">
        <button onClick={onClose}
          className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
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

      {/* body */}
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
            <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Run Details</h4>
            <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
              <StatRow label="Run ID"       value={<span className="font-mono text-[10px]">{run.run_id}</span>} />
              <StatRow label="Category"     value={run.category} />
              <StatRow label="Search Query" value={run.search_query || '—'} />
              <StatRow label="Location"     value={[run.district, run.state].filter(Boolean).join(', ') || '—'} />
              <StatRow label="Requested"    value={run.requested_count} />
              <StatRow label="Generated"    value={run.generated_count} highlight />
              <StatRow label="Source"       value={run.source === 'reddit' ? '🟠 Reddit' : '🗺 Google Maps'} />
              <StatRow label="Started"      value={fmtDate(run.started_at)} />
              <StatRow label="Completed"    value={fmtDate(run.completed_at || run.failed_at)} />
              <StatRow label="Duration"     value={fmtDur(run.duration_seconds)} />
            </div>
          </section>

          {Object.keys(stats).length > 0 && (
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-2">Statistics</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
                {stats.companies_discovered != null && <StatRow label="Discovered"         value={stats.companies_discovered} />}
                {stats.leads_generated      != null && <StatRow label="New leads generated" value={stats.leads_generated} highlight />}
                {stats.duplicates           != null && <StatRow label="Duplicates skipped"  value={stats.duplicates} />}
                {stats.with_email           != null && <StatRow label="With email"           value={stats.with_email} />}
                {stats.with_phone           != null && <StatRow label="With phone"           value={stats.with_phone} />}
                {stats.with_founder         != null && <StatRow label="With founder"         value={stats.with_founder} />}
                {stats.elapsed_seconds      != null && <StatRow label="Duration"             value={fmtDur(stats.elapsed_seconds)} />}
              </div>
            </section>
          )}

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
                            max-h-[280px] overflow-y-auto divide-y divide-slate-100/60">
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
            disabled={run.status !== 'completed' || !run.generated_count || busy}
            className="w-full inline-flex items-center justify-center gap-2 px-4 py-3
              rounded-xl text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700
              shadow-sm disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
            {busy ? (
              <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>Loading leads…</>
            ) : (
              <><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
                </svg>Load {run.generated_count} Leads into Table</>
            )}
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

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN PANEL COMPONENT
   ═══════════════════════════════════════════════════════════════════════════ */
export default function HistoryPanel({ onClose, onLoadLeads }) {
  /* ── data ── */
  const [runs,         setRuns]         = useState([])
  const [legacyCats,   setLegacyCats]   = useState([])
  const [allRunCats,   setAllRunCats]   = useState([])  // distinct category names from backend
  const [socialGroups, setSocialGroups] = useState([])
  const [loading,      setLoading]      = useState(true)
  const [loadError,    setLoadError]    = useState(null)

  /* ── filters ── */
  const [catFilter,    setCatFilter]    = useState('__all__')  // '__all__' | '__today__' | '__legacy__' | '__social__' | 'CategoryName'
  const [search,       setSearch]       = useState('')

  /* ── detail / loading state ── */
  const [detailRunId,  setDetailRunId]  = useState(null)
  const [loadingRunId, setLoadingRunId] = useState(null)
  const [loadingCat,   setLoadingCat]   = useState(null)
  const [loadingSoc,   setLoadingSoc]   = useState(null)
  const [downloading,  setDownloading]  = useState(false)
  const pollRef = useRef(null)

  /* ── fetch all ── */
  const fetchAll = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    let ok = false, err = null
    try {
      const [runsR, legR, socR] = await Promise.allSettled([
        getHistory({ per_page: 500 }),
        getLegacyCategories(),
        getSocialLeadsHistory(),
      ])
      if (runsR.status === 'fulfilled') {
        const d = runsR.value
        setRuns(d.runs ?? [])
        setAllRunCats(d.categories ?? [])
        ok = true
        if ((d.runs ?? []).some(r => r.status === 'running'))
          pollRef.current = setTimeout(() => fetchAll(true), POLL_INTERVAL_MS)
      } else {
        err = runsR.reason?.message || 'Unable to load history.'
      }
      if (legR.status === 'fulfilled') setLegacyCats(legR.value.legacy_categories ?? [])
      if (socR.status === 'fulfilled') setSocialGroups(socR.value.groups ?? [])
      setLoadError(ok ? null : err)
    } catch (e) {
      setLoadError(e?.message || 'Unable to load history. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    clearTimeout(pollRef.current)
    fetchAll()
    return () => clearTimeout(pollRef.current)
  }, [fetchAll])

  /* ── load handlers ── */
  const handleLoadRun = useCallback(async (run) => {
    setLoadingRunId(run.run_id)
    try {
      const d = await getHistoryRunLeads(run.run_id, { per_page: 500 })
      onLoadLeads(d.leads ?? [], run.category, run.run_id)
      onClose()
    } catch (e) { alert(`Failed to load: ${e.message}`) }
    finally { setLoadingRunId(null) }
  }, [onLoadLeads, onClose])

  const handleLoadLegacy = useCallback(async (entry) => {
    setLoadingCat(entry.category)
    try {
      const d = await getLegacyCategoryLeads(entry.category, { per_page: 500 })
      onLoadLeads(d.leads ?? [], entry.category, null)
      onClose()
    } catch (e) { alert(`Failed to load: ${e.message}`) }
    finally { setLoadingCat(null) }
  }, [onLoadLeads, onClose])

  const handleLoadSocial = useCallback(async (group, key) => {
    setLoadingSoc(key)
    try {
      const p = { platform: group.platform, form_id: group.form_id, per_page: 500 }
      if (group.campaign_id) p.campaign_id = group.campaign_id
      const d = await getSocialLeads(p)
      onLoadLeads(d.leads ?? [], `${group.form_name} · ${group.campaign_name || group.platform}`, null)
      onClose()
    } catch (e) { alert(`Failed to load: ${e.message}`) }
    finally { setLoadingSoc(null) }
  }, [onLoadLeads, onClose])

  const handleLoadFromDetail = useCallback((leads, cat, runId) => {
    onLoadLeads(leads, cat, runId); onClose()
  }, [onLoadLeads, onClose])

  /* ── category dropdown options ── */
  const dropdownCats = useMemo(() => {
    const s = new Set([...allRunCats, ...legacyCats.map(c => c.category)])
    return Array.from(s).sort()
  }, [allRunCats, legacyCats])

  /* ── filtered data ── */
  const filteredRuns = useMemo(() => {
    let list = [...runs]
    if (catFilter === '__today__')   list = list.filter(r => isToday(r.started_at))
    else if (catFilter === '__legacy__' || catFilter === '__social__') list = []
    else if (catFilter !== '__all__') list = list.filter(r => r.category?.toLowerCase() === catFilter.toLowerCase())
    const q = search.trim().toLowerCase()
    if (q) list = list.filter(r =>
      r.category?.toLowerCase().includes(q) ||
      r.run_id?.toLowerCase().includes(q) ||
      r.search_query?.toLowerCase().includes(q) ||
      r.state?.toLowerCase().includes(q) ||
      r.district?.toLowerCase().includes(q)
    )
    return list
  }, [runs, catFilter, search])

  const filteredLegacy = useMemo(() => {
    // Show legacy cards when:
    //  - "All History" is selected
    //  - "Legacy Data" is selected
    //  - A specific category is selected (show that category's legacy card if it exists)
    let list = legacyCats
    if (catFilter === '__social__' || catFilter === '__today__') return []
    if (catFilter !== '__all__' && catFilter !== '__legacy__') {
      // Specific category selected — only show legacy entry for that category
      list = legacyCats.filter(e => e.category?.toLowerCase() === catFilter.toLowerCase())
    }
    const q = search.trim().toLowerCase()
    return q ? list.filter(e => e.category?.toLowerCase().includes(q)) : list
  }, [legacyCats, catFilter, search])

  const filteredSocial = useMemo(() => {
    if (catFilter !== '__all__' && catFilter !== '__social__') return []
    const q = search.trim().toLowerCase()
    return q ? socialGroups.filter(g =>
      g.form_name?.toLowerCase().includes(q) ||
      g.platform?.toLowerCase().includes(q) ||
      g.category?.toLowerCase().includes(q)
    ) : socialGroups
  }, [socialGroups, catFilter, search])

  const totalItems  = filteredRuns.length + filteredLegacy.length + filteredSocial.length
  const hasRunning  = runs.some(r => r.status === 'running')
  const hasAnyData  = runs.length > 0 || legacyCats.length > 0 || socialGroups.length > 0
  const todayCount  = useMemo(() => runs.filter(r => isToday(r.started_at)).length, [runs])

  const handleDownloadAll = () => {
    setDownloading(true)
    const a = document.createElement('a'); a.href = buildAllCategoriesExcelUrl()
    a.setAttribute('download',''); document.body.appendChild(a); a.click(); document.body.removeChild(a)
    setTimeout(() => setDownloading(false), 3000)
  }

  /* ── render ── */
  return (
    <div className="fixed inset-0 z-50 flex justify-end"
         style={{ background:'rgba(15,23,42,0.55)' }}
         onClick={e => { if (e.target===e.currentTarget) onClose() }}>

      <div className="relative w-full max-w-[520px] h-full bg-white shadow-2xl flex flex-col overflow-hidden"
           style={{ animation:'slideInRight 0.22s cubic-bezier(0.25,0.46,0.45,0.94) both' }}
           onClick={e => e.stopPropagation()}>

        {/* ══ HEADER ══════════════════════════════════════════════════════ */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-white flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-sm flex-shrink-0">
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
                    <span className="font-semibold text-slate-600">{runs.length}</span> run{runs.length!==1?'s':''}
                    {todayCount > 0 && <span className="text-amber-600"> · {todayCount} today</span>}
                    {legacyCats.length > 0 && <span> · {legacyCats.reduce((s,c)=>s+c.total_leads,0).toLocaleString()} legacy leads</span>}
                  </>
                )}
                {hasRunning && (
                  <span className="ml-2 inline-flex items-center gap-1 text-sky-500 font-semibold">
                    <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse"/>live
                  </span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={() => fetchAll()} disabled={loading} title="Refresh"
              className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-500
                hover:bg-slate-100 hover:text-indigo-600 transition-colors disabled:opacity-50">
              <svg className={`w-4 h-4 ${loading?'animate-spin':''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581
                     m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
            </button>
            <button onClick={onClose}
              className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400
                hover:bg-slate-100 hover:text-slate-700 transition-colors">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>

        {/* ══ FILTERS ═════════════════════════════════════════════════════ */}
        {hasAnyData && (
          <div className="px-4 py-3 border-b border-slate-100 flex-shrink-0 space-y-2.5">

            {/* Category dropdown */}
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2a1 1 0 01-.293.707l-6.414 6.414A1 1 0 0014 13.414V19a1 1 0 01-.553.894l-4 2A1 1 0 018 21v-7.586a1 1 0 00-.293-.707L1.293 6.707A1 1 0 011 6V4z"/>
                </svg>
              </div>
              <select
                value={catFilter}
                onChange={e => { setCatFilter(e.target.value); setSearch('') }}
                className="w-full pl-8 pr-9 py-2 rounded-lg border border-slate-200 bg-white
                  text-xs font-semibold text-slate-700 appearance-none
                  focus:outline-none focus:ring-2 focus:ring-indigo-400 transition-all">
                <option value="__all__">📋 All History</option>
                {todayCount > 0 && (
                  <option value="__today__">📅 Today's Leads ({todayCount} run{todayCount!==1?'s':''})</option>
                )}
                <optgroup label="─── By Category ───">
                  {dropdownCats.map(cat => {
                    const cnt = runs.filter(r => r.category?.toLowerCase() === cat.toLowerCase()).length
                    return <option key={cat} value={cat}>{cat}{cnt > 0 ? ` (${cnt})` : ''}</option>
                  })}
                </optgroup>
                {legacyCats.length > 0 && (
                  <option value="__legacy__">📦 Legacy Data ({legacyCats.length} categor{legacyCats.length!==1?'ies':'y'})</option>
                )}
                {socialGroups.length > 0 && (
                  <option value="__social__">💬 Social Leads ({socialGroups.length} group{socialGroups.length!==1?'s':''})</option>
                )}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                </svg>
              </div>
            </div>

            {/* Source chips + Search row */}
            <div className="flex items-center gap-2">
              {/* Search */}
              <div className="relative flex-1">
                <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
                  <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                  </svg>
                </div>
                <input type="text" value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="Search by category, location, run ID…"
                  className="w-full pl-8 pr-7 py-1.5 rounded-lg border border-slate-200 bg-white
                    text-xs text-slate-800 placeholder-slate-400
                    focus:outline-none focus:ring-2 focus:ring-indigo-400 transition-all" />
                {search && (
                  <button onClick={() => setSearch('')}
                    className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-600">
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ══ DOWNLOAD ALL BANNER — sticky below filters, only on All History ══ */}
        {hasAnyData && catFilter === '__all__' && !loading && (
          <div className="px-4 py-3 bg-gradient-to-r from-emerald-50 to-teal-50
                          border-b border-emerald-200 flex-shrink-0">
            {/* total count line */}
            {(() => {
              const totalLeads = legacyCats.reduce((s,c) => s + c.total_leads, 0)
                + runs.filter(r => r.status === 'completed').reduce((s,r) => s + (r.generated_count || 0), 0)
              const catCount = new Set([
                ...legacyCats.map(c => c.category),
                ...runs.filter(r => r.status === 'completed').map(r => r.category),
              ]).size
              return (
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-bold text-emerald-800 leading-none">
                      All Leads — Category-wise Excel
                    </p>
                    <p className="text-[11px] text-emerald-600 mt-0.5">
                      {totalLeads.toLocaleString()} total leads · {catCount} categor{catCount!==1?'ies':'y'} · one sheet per category
                    </p>
                  </div>
                  <button
                    onClick={handleDownloadAll}
                    disabled={downloading || totalLeads === 0}
                    className="flex-shrink-0 inline-flex items-center gap-2 px-4 py-2.5
                      rounded-xl bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800
                      text-white text-xs font-bold shadow-sm
                      disabled:opacity-50 disabled:cursor-not-allowed
                      transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  >
                    {downloading ? (
                      <>
                        <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                        </svg>
                        Preparing…
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                        </svg>
                        Download Excel
                      </>
                    )}
                  </button>
                </div>
              )
            })()}
          </div>
        )}

        {/* ══ BODY ════════════════════════════════════════════════════════ */}
        <div className="flex-1 overflow-y-auto relative">

          {/* Full spinner — first load, no data yet */}
          {loading && !hasAnyData && (
            <div className="flex flex-col items-center justify-center py-24 gap-3">
              <svg className="w-9 h-9 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
              <p className="text-sm text-slate-500 font-medium">Loading history…</p>
              <p className="text-xs text-slate-400">Fetching all generation runs from database</p>
            </div>
          )}

          {/* Background refresh banner */}
          {loading && hasAnyData && (
            <div className="flex items-center gap-2 px-4 py-2 bg-indigo-50 border-b border-indigo-100 text-[11px] text-indigo-600">
              <svg className="w-3 h-3 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
              Refreshing history…
            </div>
          )}

          {/* Error state */}
          {loadError && !loading && !hasAnyData && (
            <div className="m-4 p-4 rounded-xl bg-rose-50 border border-rose-200 flex flex-col gap-3">
              <div className="flex items-start gap-2.5">
                <svg className="w-4 h-4 text-rose-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-rose-700 mb-0.5">Unable to load history</p>
                  <p className="text-[11px] text-rose-600 leading-relaxed">{loadError}</p>
                  <p className="text-[11px] text-rose-500 mt-1">Make sure the backend is running and MongoDB is connected.</p>
                </div>
              </div>
              <button onClick={() => fetchAll()}
                className="self-start inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                  text-xs font-semibold bg-rose-600 text-white hover:bg-rose-700 transition-colors">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                </svg>
                Retry
              </button>
            </div>
          )}

          {/* Empty state */}
          {!loading && !loadError && !hasAnyData && (
            <div className="flex flex-col items-center justify-center gap-4 py-24 px-8">
              <div className="w-16 h-16 rounded-2xl bg-slate-100 flex items-center justify-center">
                <svg className="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <div className="text-center">
                <p className="text-sm font-semibold text-slate-700">No history yet</p>
                <p className="text-xs text-slate-400 mt-2 leading-relaxed max-w-[240px]">
                  Generate some leads first — your history will appear here.
                </p>
              </div>
            </div>
          )}

          {/* ── Main content ── */}
          {hasAnyData && (
            <div className="px-4 py-3 space-y-3">

              {/* Today's Leads summary banner */}
              {catFilter === '__today__' && todayCount > 0 && (
                <div className="flex items-center gap-3 px-4 py-3 rounded-xl bg-amber-50 border border-amber-200">
                  <div className="w-8 h-8 rounded-xl bg-amber-100 flex items-center justify-center flex-shrink-0">
                    <svg className="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                    </svg>
                  </div>
                  <div>
                    <p className="text-sm font-bold text-amber-800">Today's Runs — {todayStr()}</p>
                    <p className="text-xs text-amber-600">
                      {todayCount} generation run{todayCount!==1?'s':''} · {filteredRuns.reduce((s,r)=>s+(r.generated_count||0),0)} leads generated today
                    </p>
                  </div>
                </div>
              )}

              {/* No search results */}
              {search && totalItems === 0 && (
                <div className="flex flex-col items-center py-10 gap-2">
                  <p className="text-sm font-semibold text-slate-600">No results for "{search}"</p>
                  <button onClick={() => setSearch('')}
                    className="text-xs text-indigo-500 hover:underline">Clear search</button>
                </div>
              )}

              {/* Generation runs */}
              {filteredRuns.length > 0 && (
                <>
                  {catFilter === '__all__' && filteredLegacy.length > 0 && (
                    <p className="text-[11px] font-bold text-slate-400 uppercase tracking-widest pt-1">
                      Generation Runs ({filteredRuns.length})
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

              {/* No runs in this filter */}
              {catFilter !== '__legacy__' && catFilter !== '__social__' &&
               !search && filteredRuns.length === 0 && hasAnyData && !loading && (
                <div className="flex flex-col items-center py-10 gap-2 text-center">
                  <svg className="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                      d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                  </svg>
                  <p className="text-sm font-semibold text-slate-500">
                    {catFilter === '__today__' ? 'No runs today yet' : 'No runs for this category yet'}
                  </p>
                  <p className="text-xs text-slate-400">Generate leads to see them here.</p>
                </div>
              )}

              {/* Legacy section */}
              {filteredLegacy.length > 0 && (
                <>
                  <div className="flex items-center gap-3 pt-2">
                    <div className="flex-1 h-px bg-amber-200" />
                    <span className="text-[11px] font-bold text-amber-500 uppercase tracking-widest whitespace-nowrap">
                      Legacy Data
                    </span>
                    <div className="flex-1 h-px bg-amber-200" />
                  </div>
                  {catFilter === '__legacy__' && (
                    <p className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-center">
                      Leads stored before the history feature was added — not linked to a specific run.
                    </p>
                  )}
                  {filteredLegacy.map(entry => (
                    <LegacyCard key={entry.category} entry={entry}
                      onLoadData={handleLoadLegacy} loadingCat={loadingCat} />
                  ))}
                </>
              )}

              {/* Social section */}
              {filteredSocial.length > 0 && (
                <>
                  <div className="flex items-center gap-3 pt-2">
                    <div className="flex-1 h-px bg-violet-200" />
                    <span className="text-[11px] font-bold text-violet-500 uppercase tracking-widest whitespace-nowrap">
                      Social Leads
                    </span>
                    <div className="flex-1 h-px bg-violet-200" />
                  </div>
                  {filteredSocial.map((group, i) => (
                    <SocialCard
                      key={`${group.platform}-${group.form_id}-${group.campaign_id||i}`}
                      group={group} onViewLeads={handleLoadSocial} loadingKey={loadingSoc} />
                  ))}
                </>
              )}

              {/* Footer count */}
              {totalItems > 0 && (
                <p className="text-center text-[11px] text-slate-300 pb-2 pt-1">
                  {totalItems} item{totalItems!==1?'s':''} shown
                  {search && ` · matching "${search}"`}
                </p>
              )}
            </div>
          )}

          {/* RunDetail overlay */}
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
