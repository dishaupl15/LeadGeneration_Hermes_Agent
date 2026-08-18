/**
 * SocialLeads.jsx — Phase 3 Production-Ready
 * ─────────────────────────────────────────────
 * Social Leads CRM dashboard.
 *
 * Features:
 *  - Platform stat cards (Total / LinkedIn / X / WhatsApp / Facebook / Website / Other)
 *  - Sidebar filters: Category → Form → Campaign (cascading, server-side)
 *  - Server-side search, sort, pagination (never loads everything client-side)
 *  - Export CSV (respects all active filters)
 *  - Lead detail slide-in panel with: person fields, ALL form answers,
 *    event timeline, enrichment status
 *  - Seed test-data button (dev/QA)
 *  - Clear all filters
 *  - History is integrated through the unified HistoryPanel in LeadGeneration
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import {
  getSocialLeads,
  getSocialLeadsStats,
  getSocialLead,
  seedSocialLeadsTestData,
  exportSocialLeads,
} from '../services/api'

/* ── Platform meta ──────────────────────────────────────────────────────────── */
const PLATFORMS = [
  { id: 'all',      label: 'All',       icon: '⚡', color: 'indigo' },
  { id: 'linkedin', label: 'LinkedIn',  icon: '💼', color: 'sky'    },
  { id: 'x',        label: 'X',         icon: '𝕏',  color: 'slate'  },
  { id: 'whatsapp', label: 'WhatsApp',  icon: '💬', color: 'green'  },
  { id: 'facebook', label: 'Facebook',  icon: '👥', color: 'blue'   },
  { id: 'website',  label: 'Website',   icon: '🌐', color: 'violet' },
  { id: 'other',    label: 'Other',     icon: '🔗', color: 'slate'  },
]

const PLT_STYLES = {
  indigo: { tab: 'bg-indigo-600 text-white shadow-md', badge: 'bg-indigo-50 border-indigo-200 text-indigo-700', dot: 'bg-indigo-400' },
  sky:    { tab: 'bg-sky-500 text-white shadow-md',    badge: 'bg-sky-50 border-sky-200 text-sky-700',       dot: 'bg-sky-400'    },
  slate:  { tab: 'bg-slate-700 text-white shadow-md',  badge: 'bg-slate-100 border-slate-200 text-slate-700', dot: 'bg-slate-400'  },
  green:  { tab: 'bg-green-600 text-white shadow-md',  badge: 'bg-green-50 border-green-200 text-green-700',  dot: 'bg-green-400'  },
  blue:   { tab: 'bg-blue-600 text-white shadow-md',   badge: 'bg-blue-50 border-blue-200 text-blue-700',     dot: 'bg-blue-400'   },
  violet: { tab: 'bg-violet-600 text-white shadow-md', badge: 'bg-violet-50 border-violet-200 text-violet-700', dot: 'bg-violet-400' },
}

/* ── Enrichment status ──────────────────────────────────────────────────────── */
const ENRICH_STYLES = {
  pending:       { label: 'Pending',       cls: 'bg-slate-100 text-slate-500 border-slate-200' },
  processing:    { label: 'Processing',    cls: 'bg-sky-50 text-sky-600 border-sky-200 animate-pulse' },
  completed:     { label: 'Enriched',      cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  failed:        { label: 'Failed',        cls: 'bg-rose-50 text-rose-600 border-rose-200' },
  not_requested: { label: 'Not requested', cls: 'bg-slate-50 text-slate-400 border-slate-100' },
}

/* ── Event timeline colours ─────────────────────────────────────────────────── */
const EVENT_STYLES = {
  FORM_OPENED:          { dot: 'bg-slate-400',    label: 'Form Opened' },
  FORM_SUBMITTED:       { dot: 'bg-indigo-500',   label: 'Form Submitted' },
  VALIDATION_SUCCESS:   { dot: 'bg-emerald-500',  label: 'Validation Passed' },
  LEAD_SAVED:           { dot: 'bg-teal-500',     label: 'Lead Saved' },
  ENRICHMENT_STARTED:   { dot: 'bg-sky-500',      label: 'Enrichment Started' },
  ENRICHMENT_COMPLETED: { dot: 'bg-violet-500',   label: 'Enrichment Complete' },
  ENRICHMENT_FAILED:    { dot: 'bg-rose-500',     label: 'Enrichment Failed' },
}

/* ── helpers ────────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: true,
    }).format(new Date(iso))
  } catch { return iso?.slice(0, 16) ?? '—' }
}

function getPlatformMeta(id) {
  return PLATFORMS.find(p => p.id === id) ?? PLATFORMS[PLATFORMS.length - 1]
}

/* ── PlatformBadge ──────────────────────────────────────────────────────────── */
function PlatformBadge({ platform }) {
  const p = getPlatformMeta(platform)
  const s = PLT_STYLES[p.color] ?? PLT_STYLES.slate
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[11px] font-semibold ${s.badge}`}>
      <span>{p.icon}</span>{p.label}
    </span>
  )
}

/* ── EnrichmentBadge ────────────────────────────────────────────────────────── */
function EnrichmentBadge({ status }) {
  const s = ENRICH_STYLES[status] ?? ENRICH_STYLES.not_requested
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-semibold ${s.cls}`}>
      {s.label}
    </span>
  )
}

/* ── StatCard ───────────────────────────────────────────────────────────────── */
function StatCard({ icon, label, value, active, onClick, color = 'indigo' }) {
  const s = PLT_STYLES[color] ?? PLT_STYLES.indigo
  return (
    <button onClick={onClick}
      className={`flex items-center gap-3 p-4 rounded-2xl border transition-all text-left w-full
                  ${active
                    ? `${s.tab} border-transparent`
                    : 'bg-white border-slate-200 hover:border-indigo-300 hover:shadow-sm'}`}>
      <span className="text-2xl">{icon}</span>
      <div>
        <p className={`text-xl font-bold ${active ? 'text-white' : 'text-slate-800'}`}>{value ?? 0}</p>
        <p className={`text-xs font-medium ${active ? 'text-white/80' : 'text-slate-500'}`}>{label}</p>
      </div>
    </button>
  )
}

/* ── FilterChip ─────────────────────────────────────────────────────────────── */
function FilterChip({ label, count, active, onClick }) {
  return (
    <button onClick={onClick}
      className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold
                  border transition-all whitespace-nowrap
                  ${active
                    ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm'
                    : 'bg-white border-slate-200 text-slate-600 hover:bg-indigo-50 hover:border-indigo-300 hover:text-indigo-700'}`}>
      {label}
      {count != null && (
        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-bold min-w-[20px] text-center
                          ${active ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'}`}>
          {count}
        </span>
      )}
    </button>
  )
}

/* ── EventTimeline ──────────────────────────────────────────────────────────── */
function EventTimeline({ events }) {
  if (!events?.length) return (
    <p className="text-xs text-slate-400 italic">No events recorded.</p>
  )
  return (
    <div className="relative pl-5 space-y-3">
      {/* vertical line */}
      <div className="absolute left-1.5 top-2 bottom-2 w-px bg-slate-200" />
      {events.map((ev, i) => {
        const style = EVENT_STYLES[ev.event] ?? { dot: 'bg-slate-300', label: ev.event }
        return (
          <div key={i} className="relative flex items-start gap-3">
            <span className={`absolute -left-3.5 mt-0.5 w-2.5 h-2.5 rounded-full border-2 border-white flex-shrink-0 ${style.dot}`} />
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-bold text-slate-700">{style.label}</span>
                <span className="text-[10px] text-slate-400">{fmtDate(ev.timestamp)}</span>
              </div>
              {ev.message && (
                <p className="text-[11px] text-slate-500 mt-0.5 leading-snug">{ev.message}</p>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

/* ── LeadDetailPanel ────────────────────────────────────────────────────────── */
function LeadDetailPanel({ submissionId, onClose }) {
  const [lead,    setLead]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    getSocialLead(submissionId)
      .then(d => setLead(d.lead))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [submissionId])

  const handleBackdrop = (e) => { if (e.target === e.currentTarget) onClose() }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: 'rgba(15,23,42,0.5)' }}
      onClick={handleBackdrop}
    >
      <div
        className="w-full max-w-[500px] h-full bg-white shadow-2xl flex flex-col overflow-hidden"
        style={{ animation: 'slideInRight 0.2s ease both' }}
        onClick={e => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200 flex-shrink-0">
          <button onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-lg
                       text-slate-400 hover:bg-slate-100 transition-colors">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
          <h3 className="text-sm font-bold text-slate-900 flex-1">Lead Details</h3>
          {lead && <PlatformBadge platform={lead.platform} />}
          {lead && <EnrichmentBadge status={lead.enrichment_status} />}
        </div>

        {/* loading */}
        {loading && (
          <div className="flex-1 flex items-center justify-center">
            <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          </div>
        )}

        {/* error */}
        {!loading && error && (
          <div className="m-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700">
            {error}
          </div>
        )}

        {/* content */}
        {!loading && lead && (
          <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5 scrollbar-thin">

            {/* ── Person ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Person</h4>
              <div className="space-y-2">
                {[
                  { label: 'Name',        value: lead.person?.name },
                  { label: 'Email',       value: lead.person?.email },
                  { label: 'Phone',       value: lead.person?.phone },
                  { label: 'Company',     value: lead.person?.company },
                  { label: 'Designation', value: lead.person?.designation },
                ].filter(f => f.value).map(({ label, value }) => (
                  <div key={label}
                    className="flex items-start gap-3 px-3 py-2.5 rounded-xl bg-slate-50 border border-slate-100">
                    <span className="text-[11px] font-semibold text-slate-400 w-24 flex-shrink-0 mt-0.5">{label}</span>
                    <span className="text-sm text-slate-800 font-medium break-all">{value}</span>
                  </div>
                ))}
              </div>
            </section>

            {/* ── Source Attribution ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Source Attribution</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
                {[
                  { label: 'Platform',     value: <PlatformBadge platform={lead.platform} /> },
                  { label: 'Category',     value: lead.category || '—' },
                  { label: 'Form',         value: lead.form_name || '—' },
                  { label: 'Form Version', value: lead.form_version ? `v${lead.form_version}` : '—' },
                  { label: 'Campaign',     value: lead.campaign_name || '—' },
                  { label: 'Campaign ID',  value: lead.campaign_id
                      ? <span className="font-mono text-[10px]">{lead.campaign_id}</span>
                      : '—' },
                  { label: 'Submission ID', value: <span className="font-mono text-[10px]">{lead.submission_id}</span> },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between py-2 gap-4">
                    <span className="text-xs text-slate-500 flex-shrink-0">{label}</span>
                    <span className="text-xs font-semibold text-slate-800 text-right">{value}</span>
                  </div>
                ))}
              </div>
            </section>

            {/* ── Timing ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Timing</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
                {[
                  { label: 'Submitted At',    value: fmtDate(lead.submitted_at) },
                  { label: 'Landing At',      value: lead.landing_timestamp ? fmtDate(lead.landing_timestamp) : '—' },
                  { label: 'Created At',      value: fmtDate(lead.created_at) },
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between py-2">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className="text-xs font-semibold text-slate-800">{value}</span>
                  </div>
                ))}
              </div>
            </section>

            {/* ── Form Answers ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">
                Form Answers ({lead.answers?.length ?? 0})
              </h4>
              <div className="space-y-2">
                {(lead.answers ?? []).map((ans, i) => (
                  <div key={i} className="rounded-xl border border-slate-100 bg-white px-4 py-3">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">
                      {ans.label}
                      <span className="ml-1.5 font-normal normal-case text-slate-300">{ans.type}</span>
                    </p>
                    <p className="text-sm text-slate-800">
                      {Array.isArray(ans.value)
                        ? ans.value.join(', ')
                        : (ans.value ?? '—')}
                    </p>
                  </div>
                ))}
                {!lead.answers?.length && (
                  <p className="text-xs text-slate-400 italic">No answers stored.</p>
                )}
              </div>
            </section>

            {/* ── Enrichment Status ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Enrichment</h4>
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 px-4 py-1 divide-y divide-slate-100">
                <div className="flex items-center justify-between py-2">
                  <span className="text-xs text-slate-500">Status</span>
                  <EnrichmentBadge status={lead.enrichment_status} />
                </div>
                {lead.enrichment_started_at && (
                  <div className="flex items-center justify-between py-2">
                    <span className="text-xs text-slate-500">Started</span>
                    <span className="text-xs font-semibold text-slate-800">{fmtDate(lead.enrichment_started_at)}</span>
                  </div>
                )}
                {lead.enrichment_completed_at && (
                  <div className="flex items-center justify-between py-2">
                    <span className="text-xs text-slate-500">Completed</span>
                    <span className="text-xs font-semibold text-slate-800">{fmtDate(lead.enrichment_completed_at)}</span>
                  </div>
                )}
                {lead.enrichment_error && (
                  <div className="py-2">
                    <span className="text-xs text-rose-500">{lead.enrichment_error}</span>
                  </div>
                )}
              </div>
            </section>

            {/* ── Event Timeline ── */}
            <section>
              <h4 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">
                Event Timeline ({lead.events?.length ?? 0})
              </h4>
              <EventTimeline events={lead.events} />
            </section>

          </div>
        )}
      </div>
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0.8; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  )
}

/* ── LeadsTable ─────────────────────────────────────────────────────────────── */
function LeadsTable({ leads, loading, onSelectLead }) {
  if (loading) return (
    <div className="flex items-center justify-center py-16 gap-3 text-slate-400">
      <svg className="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
      </svg>
      <span className="text-sm">Loading leads…</span>
    </div>
  )

  if (!leads.length) return (
    <div className="text-center py-16 px-4">
      <div className="w-14 h-14 rounded-2xl bg-slate-100 flex items-center justify-center mx-auto mb-3">
        <svg className="w-7 h-7 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857
               M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857
               m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
        </svg>
      </div>
      <p className="text-sm font-semibold text-slate-600">No leads match your current filters</p>
      <p className="text-xs text-slate-400 mt-1">
        Try adjusting filters, or click <strong>Seed Test Data</strong> to create sample leads.
      </p>
    </div>
  )

  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-left" style={{ minWidth: '920px' }}>
        <thead>
          <tr className="bg-slate-50 border-b-2 border-slate-200">
            {['#', 'Name', 'Email', 'Phone', 'Company', 'Designation', 'Platform', 'Category', 'Form', 'Campaign', 'Submitted'].map(h => (
              <th key={h}
                className="px-4 py-3 text-[11px] font-bold text-slate-500 uppercase tracking-widest whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {leads.map((lead, i) => (
            <tr key={lead.submission_id}
              onClick={() => onSelectLead(lead.submission_id)}
              className={`border-b border-slate-100 cursor-pointer transition-colors
                         ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'}
                         hover:bg-indigo-50/60`}>
              <td className="px-4 py-3 text-xs text-slate-400">{i + 1}</td>
              <td className="px-4 py-3">
                <span className="text-sm font-semibold text-slate-800">
                  {lead.person?.name || <span className="text-slate-300 italic text-xs">—</span>}
                </span>
              </td>
              <td className="px-4 py-3 text-sm text-indigo-600 max-w-[180px] truncate">
                {lead.person?.email || <span className="text-slate-300 italic text-xs">—</span>}
              </td>
              <td className="px-4 py-3 text-sm text-slate-700 whitespace-nowrap">
                {lead.person?.phone || <span className="text-slate-300 italic text-xs">—</span>}
              </td>
              <td className="px-4 py-3 text-sm text-slate-700 max-w-[140px] truncate">
                {lead.person?.company || <span className="text-slate-300 italic text-xs">—</span>}
              </td>
              <td className="px-4 py-3 text-sm text-slate-600 max-w-[120px] truncate">
                {lead.person?.designation || <span className="text-slate-300 italic text-xs">—</span>}
              </td>
              <td className="px-4 py-3 whitespace-nowrap">
                <PlatformBadge platform={lead.platform} />
              </td>
              <td className="px-4 py-3 text-xs text-slate-600 max-w-[120px] truncate">
                {lead.category || '—'}
              </td>
              <td className="px-4 py-3 text-xs text-slate-600 max-w-[140px] truncate" title={lead.form_name}>
                {lead.form_name || '—'}
              </td>
              <td className="px-4 py-3 text-xs text-slate-500 max-w-[140px] truncate" title={lead.campaign_name}>
                {lead.campaign_name || '—'}
              </td>
              <td className="px-4 py-3 text-xs text-slate-400 whitespace-nowrap">
                {fmtDate(lead.submitted_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════════════════════ */
export default function SocialLeads() {

  /* ── filter state ───────────────────────────────────────────────────────── */
  const [activePlatform,   setActivePlatform]   = useState('all')
  const [activeCategory,   setActiveCategory]   = useState('')
  const [activeFormId,     setActiveFormId]     = useState('')
  const [activeCampaignId, setActiveCampaignId] = useState('')
  const [search,           setSearch]           = useState('')
  const [sortBy,           setSortBy]           = useState('submitted_at')
  const [sortDir,          setSortDir]          = useState(-1)
  const [page,             setPage]             = useState(1)
  const PER_PAGE = 50

  /* ── data state ─────────────────────────────────────────────────────────── */
  const [stats,         setStats]         = useState(null)
  const [leads,         setLeads]         = useState([])
  const [total,         setTotal]         = useState(0)
  const [loadingStats,  setLoadingStats]  = useState(true)
  const [loadingLeads,  setLoadingLeads]  = useState(false)
  const [selectedSubId, setSelectedSubId] = useState(null)
  const [seeding,       setSeeding]       = useState(false)
  const [seedMsg,       setSeedMsg]       = useState(null)
  const [exporting,     setExporting]     = useState(false)

  /* ── build API filter params ────────────────────────────────────────────── */
  const filterParams = useMemo(() => {
    const p = {}
    if (activePlatform !== 'all') p.platform    = activePlatform
    if (activeCategory)           p.category    = activeCategory
    if (activeFormId)             p.form_id     = activeFormId
    if (activeCampaignId)         p.campaign_id = activeCampaignId
    if (search.trim())            p.search      = search.trim()
    return p
  }, [activePlatform, activeCategory, activeFormId, activeCampaignId, search])

  /* ── fetch stats ────────────────────────────────────────────────────────── */
  const fetchStats = useCallback(async () => {
    setLoadingStats(true)
    try {
      const data = await getSocialLeadsStats(filterParams)
      setStats(data)
    } catch (err) { console.error('[stats]', err) }
    finally { setLoadingStats(false) }
  }, [filterParams])

  /* ── fetch leads ────────────────────────────────────────────────────────── */
  const fetchLeads = useCallback(async () => {
    setLoadingLeads(true)
    try {
      const data = await getSocialLeads({
        ...filterParams,
        sort_by:  sortBy,
        sort_dir: sortDir,
        page,
        per_page: PER_PAGE,
      })
      setLeads(data.leads ?? [])
      setTotal(data.total ?? 0)
    } catch (err) { console.error('[leads]', err) }
    finally { setLoadingLeads(false) }
  }, [filterParams, sortBy, sortDir, page])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => { fetchLeads() }, [fetchLeads])

  /* ── filter change handlers (cascading reset) ───────────────────────────── */
  const handlePlatformChange = (p) => {
    setActivePlatform(p)
    setActiveCategory('')
    setActiveFormId('')
    setActiveCampaignId('')
    setPage(1)
  }
  const handleCategoryChange = (c) => {
    setActiveCategory(c)
    setActiveFormId('')
    setActiveCampaignId('')
    setPage(1)
  }
  const handleFormChange = (fid) => {
    setActiveFormId(fid)
    setActiveCampaignId('')
    setPage(1)
  }
  const handleCampaignChange = (cid) => { setActiveCampaignId(cid); setPage(1) }

  const clearAllFilters = () => {
    setActivePlatform('all')
    setActiveCategory('')
    setActiveFormId('')
    setActiveCampaignId('')
    setSearch('')
    setPage(1)
  }

  /* ── sort toggle ────────────────────────────────────────────────────────── */
  const handleSort = (field) => {
    if (sortBy === field) setSortDir(d => d === -1 ? 1 : -1)
    else { setSortBy(field); setSortDir(-1) }
    setPage(1)
  }

  /* ── seed test data ─────────────────────────────────────────────────────── */
  const handleSeed = async () => {
    setSeeding(true)
    setSeedMsg(null)
    try {
      const res = await seedSocialLeadsTestData({ clear_existing: false })
      setSeedMsg(res.message)
      fetchStats()
      fetchLeads()
    } catch (err) {
      setSeedMsg(`Error: ${err.message}`)
    } finally {
      setSeeding(false)
      setTimeout(() => setSeedMsg(null), 5000)
    }
  }

  /* ── CSV export ─────────────────────────────────────────────────────────── */
  const handleExport = () => {
    setExporting(true)
    try {
      // exportSocialLeads() returns the full URL — trigger download directly
      const url = exportSocialLeads(filterParams)
      const a   = document.createElement('a')
      a.href    = url
      a.download = ''
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } catch (err) {
      alert(`Export failed: ${err.message}`)
    } finally {
      setTimeout(() => setExporting(false), 1500)
    }
  }

  /* ── derived data ───────────────────────────────────────────────────────── */
  const totalPages    = Math.ceil(total / PER_PAGE)
  const platformCounts = stats?.platform_counts ?? {}
  const categoryList   = stats?.category_counts ?? []
  const formList       = stats?.form_counts     ?? []
  const campaignList   = stats?.campaign_counts ?? []
  const hasFilters     = activePlatform !== 'all' || activeCategory || activeFormId || activeCampaignId || search

  /* ── table title ────────────────────────────────────────────────────────── */
  const tableTitle = (() => {
    const parts = []
    if (activePlatform !== 'all') parts.push(`${getPlatformMeta(activePlatform).icon} ${getPlatformMeta(activePlatform).label}`)
    if (activeCategory) parts.push(activeCategory)
    if (activeFormId) {
      const f = formList.find(f => f.form_id === activeFormId)
      if (f) parts.push(f.form_name)
    }
    if (activeCampaignId) {
      const c = campaignList.find(c => c.campaign_id === activeCampaignId)
      if (c) parts.push(c.campaign_name || c.campaign_id)
    }
    return parts.length ? parts.join(' · ') : 'All Social Leads'
  })()

  /* ════════════════════════════════════════════════════════════════════════ */
  const navigate = useNavigate()
  return (
    <Layout onOpenFollowUps={() => navigate('/follow-ups')}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">

        {/* Page header */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Social Leads</h1>
            <p className="text-sm text-slate-500 mt-1">Leads collected from forms and social platforms.</p>
          </div>
          <div className="flex items-center gap-2">
            {/* Export */}
            <button
              onClick={handleExport}
              disabled={exporting || total === 0}
              className="btn-secondary px-3 py-2 text-xs gap-1.5 disabled:opacity-40 disabled:cursor-not-allowed">
              {exporting
                ? <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                : <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                  </svg>
              }
              {exporting ? 'Exporting…' : 'Export CSV'}
            </button>
            {/* Seed test data */}
            <button onClick={handleSeed} disabled={seeding}
              className="btn-secondary px-3 py-2 text-xs gap-1.5 disabled:opacity-50">
              {seeding ? '…' : '🌱'} {seeding ? 'Seeding…' : 'Seed Test Data'}
            </button>
          </div>
        </div>

        {/* Seed message */}
        {seedMsg && (
          <div className={`mb-4 px-4 py-3 rounded-xl border text-xs font-semibold
                           ${seedMsg.startsWith('Error')
                             ? 'bg-rose-50 border-rose-200 text-rose-700'
                             : 'bg-emerald-50 border-emerald-200 text-emerald-700'}`}>
            {seedMsg}
          </div>
        )}

        {/* ── PLATFORM STAT CARDS ──────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-7">
          {PLATFORMS.map(p => (
            <StatCard
              key={p.id}
              icon={p.icon}
              label={p.label}
              value={p.id === 'all' ? (stats?.total ?? 0) : (platformCounts[p.id] ?? 0)}
              active={activePlatform === p.id}
              onClick={() => handlePlatformChange(p.id)}
              color={p.color}
            />
          ))}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">

          {/* ── LEFT FILTERS SIDEBAR ──────────────────────────────────────── */}
          <div className="lg:col-span-1 space-y-4">

            {/* Category */}
            {categoryList.length > 0 && (
              <div className="crm-card p-4">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Category</h3>
                <div className="flex flex-wrap gap-1.5">
                  <FilterChip label="All" count={stats?.total} active={!activeCategory}
                    onClick={() => handleCategoryChange('')} />
                  {categoryList.map(c => (
                    <FilterChip key={c.category} label={c.category} count={c.count}
                      active={activeCategory === c.category}
                      onClick={() => handleCategoryChange(activeCategory === c.category ? '' : c.category)} />
                  ))}
                </div>
              </div>
            )}

            {/* Form */}
            {formList.length > 0 && (
              <div className="crm-card p-4">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Form</h3>
                <div className="flex flex-col gap-1.5">
                  {formList.map(f => (
                    <button key={f.form_id}
                      onClick={() => handleFormChange(activeFormId === f.form_id ? '' : f.form_id)}
                      className={`flex items-center justify-between w-full px-3 py-2 rounded-xl
                                  text-xs font-semibold text-left transition-all border
                                  ${activeFormId === f.form_id
                                    ? 'bg-indigo-600 border-indigo-600 text-white'
                                    : 'bg-white border-slate-200 text-slate-700 hover:bg-indigo-50 hover:border-indigo-300'}`}>
                      <span className="truncate pr-2">{f.form_name}</span>
                      <span className={`flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded-full
                                        ${activeFormId === f.form_id ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'}`}>
                        {f.count}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Campaign */}
            {campaignList.length > 0 && (
              <div className="crm-card p-4">
                <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Campaign</h3>
                <div className="flex flex-col gap-1.5">
                  {campaignList.map(c => (
                    <button key={c.campaign_id}
                      onClick={() => handleCampaignChange(activeCampaignId === c.campaign_id ? '' : c.campaign_id)}
                      className={`flex items-center justify-between w-full px-3 py-2 rounded-xl
                                  text-xs font-semibold text-left transition-all border
                                  ${activeCampaignId === c.campaign_id
                                    ? 'bg-indigo-600 border-indigo-600 text-white'
                                    : 'bg-white border-slate-200 text-slate-700 hover:bg-indigo-50 hover:border-indigo-300'}`}>
                      <span className="truncate pr-2">{c.campaign_name || c.campaign_id}</span>
                      <span className={`flex-shrink-0 text-[10px] font-bold px-1.5 py-0.5 rounded-full
                                        ${activeCampaignId === c.campaign_id ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-500'}`}>
                        {c.count}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Sort controls */}
            <div className="crm-card p-4">
              <h3 className="text-[11px] font-bold text-slate-400 uppercase tracking-widest mb-3">Sort</h3>
              <div className="flex flex-col gap-1.5">
                {[
                  { value: 'submitted_at', label: 'Submitted Date' },
                  { value: 'person.name',  label: 'Name' },
                  { value: 'platform',     label: 'Platform' },
                  { value: 'category',     label: 'Category' },
                ].map(opt => (
                  <button key={opt.value}
                    onClick={() => handleSort(opt.value)}
                    className={`flex items-center justify-between w-full px-3 py-2 rounded-xl
                                text-xs font-semibold text-left transition-all border
                                ${sortBy === opt.value
                                  ? 'bg-slate-700 border-slate-700 text-white'
                                  : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50'}`}>
                    <span>{opt.label}</span>
                    {sortBy === opt.value && (
                      <span className="text-slate-300 text-[10px]">
                        {sortDir === -1 ? '↓ Newest' : '↑ Oldest'}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            </div>

            {/* Empty sidebar */}
            {!loadingStats && categoryList.length === 0 && (
              <div className="crm-card p-6 text-center">
                <p className="text-xs text-slate-400">No filter data available yet.</p>
                <p className="text-xs text-slate-300 mt-1">Submit a form or click Seed Test Data.</p>
              </div>
            )}
          </div>

          {/* ── RIGHT — LEADS TABLE ───────────────────────────────────────── */}
          <div className="lg:col-span-3">
            <div className="crm-card overflow-hidden">

              {/* Table toolbar */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between
                              gap-3 px-5 py-4 border-b border-slate-100">
                <div>
                  <h2 className="text-sm font-bold text-slate-800">{tableTitle}</h2>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {total} lead{total !== 1 ? 's' : ''}
                    {total > PER_PAGE && ` · page ${page} of ${totalPages}`}
                    {loadingLeads && ' · refreshing…'}
                  </p>
                </div>

                {/* Search */}
                <div className="relative w-full sm:w-64 flex-shrink-0">
                  <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                    <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                    </svg>
                  </div>
                  <input
                    type="text"
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1) }}
                    placeholder="Search name, email, company…"
                    className="w-full rounded-xl border border-slate-200 bg-white
                               pl-8 pr-8 py-2 text-xs text-slate-800 placeholder-slate-400
                               focus:outline-none focus:ring-2 focus:ring-indigo-400 transition-all"
                  />
                  {search && (
                    <button
                      onClick={() => { setSearch(''); setPage(1) }}
                      className="absolute inset-y-0 right-2 flex items-center text-slate-400 hover:text-slate-600">
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                      </svg>
                    </button>
                  )}
                </div>
              </div>

              {/* Active filter breadcrumbs */}
              {hasFilters && (
                <div className="flex flex-wrap items-center gap-2 px-5 py-2.5
                                bg-indigo-50/50 border-b border-indigo-100">
                  <span className="text-[11px] text-slate-500 font-semibold">Filters:</span>

                  {activePlatform !== 'all' && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5
                                     rounded-full bg-white border border-indigo-200 text-indigo-700">
                      {getPlatformMeta(activePlatform).icon} {getPlatformMeta(activePlatform).label}
                      <button onClick={() => handlePlatformChange('all')}
                        className="ml-0.5 text-indigo-400 hover:text-indigo-700">×</button>
                    </span>
                  )}
                  {activeCategory && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5
                                     rounded-full bg-white border border-indigo-200 text-indigo-700">
                      {activeCategory}
                      <button onClick={() => handleCategoryChange('')}
                        className="ml-0.5 text-indigo-400 hover:text-indigo-700">×</button>
                    </span>
                  )}
                  {activeFormId && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5
                                     rounded-full bg-white border border-indigo-200 text-indigo-700">
                      {formList.find(f => f.form_id === activeFormId)?.form_name ?? activeFormId}
                      <button onClick={() => handleFormChange('')}
                        className="ml-0.5 text-indigo-400 hover:text-indigo-700">×</button>
                    </span>
                  )}
                  {activeCampaignId && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5
                                     rounded-full bg-white border border-indigo-200 text-indigo-700">
                      {campaignList.find(c => c.campaign_id === activeCampaignId)?.campaign_name ?? activeCampaignId}
                      <button onClick={() => handleCampaignChange('')}
                        className="ml-0.5 text-indigo-400 hover:text-indigo-700">×</button>
                    </span>
                  )}
                  {search && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5
                                     rounded-full bg-white border border-indigo-200 text-indigo-700">
                      "{search}"
                      <button onClick={() => { setSearch(''); setPage(1) }}
                        className="ml-0.5 text-indigo-400 hover:text-indigo-700">×</button>
                    </span>
                  )}

                  <button
                    onClick={clearAllFilters}
                    className="ml-auto text-[11px] text-slate-400 hover:text-rose-600 font-semibold">
                    Clear all
                  </button>
                </div>
              )}

              {/* Table */}
              <LeadsTable
                leads={leads}
                loading={loadingLeads}
                onSelectLead={setSelectedSubId}
              />

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-5 py-3
                                border-t border-slate-100 bg-slate-50/70">
                  <span className="text-xs text-slate-500">
                    Showing {(page - 1) * PER_PAGE + 1}–{Math.min(page * PER_PAGE, total)} of {total}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200
                                 bg-white text-slate-600 hover:bg-indigo-50
                                 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                      ← Prev
                    </button>
                    <span className="text-xs text-slate-500 font-semibold min-w-[60px] text-center">
                      {page} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                      className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-slate-200
                                 bg-white text-slate-600 hover:bg-indigo-50
                                 disabled:opacity-40 disabled:cursor-not-allowed transition-colors">
                      Next →
                    </button>
                  </div>
                </div>
              )}

              {/* Footer hint */}
              {leads.length > 0 && (
                <div className="px-5 py-2.5 border-t border-slate-100 bg-slate-50/70
                                flex items-center justify-between gap-2">
                  <span className="text-[11px] text-slate-400">
                    Click any row to view full lead details · All data from MongoDB
                  </span>
                  {hasFilters && total > 0 && (
                    <button
                      onClick={handleExport}
                      disabled={exporting}
                      className="text-[11px] text-emerald-600 hover:text-emerald-800 font-semibold
                                 flex items-center gap-1 flex-shrink-0">
                      <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                          d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                      </svg>
                      Export {total} leads
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Lead detail slide-in panel */}
      {selectedSubId && (
        <LeadDetailPanel
          submissionId={selectedSubId}
          onClose={() => setSelectedSubId(null)}
        />
      )}
    </Layout>
  )
}
