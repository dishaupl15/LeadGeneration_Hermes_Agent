/**
 * FollowUps.jsx  —  /follow-ups
 * ──────────────────────────────
 * Dedicated follow-ups page. Shows overdue, due today, and upcoming
 * follow-ups with clear visual separation and Mark Done actions.
 *
 * All data comes from GET /leads/follow-ups — same API used by FollowUpsPanel.
 * No fake data.
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { getFollowUps, markFollowUpCompleted } from '../services/api'

/* ── helpers ──────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    }).format(new Date(iso))
  } catch { return iso?.slice(0, 10) ?? '—' }
}

/* ── Status badge ─────────────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const m = {
    interested:     'bg-emerald-50 text-emerald-700 border-emerald-200',
    not_interested: 'bg-rose-50 text-rose-700 border-rose-200',
    new:            'bg-sky-50 text-sky-600 border-sky-200',
  }
  const labels = { interested: 'Interested', not_interested: 'Not Interested', new: 'New' }
  return (
    <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${m[status] || m.new}`}>
      {labels[status] || 'New'}
    </span>
  )
}

/* ── Section header ───────────────────────────────────────────────────────── */
function SectionHeader({ label, count, accent }) {
  if (!count) return null
  return (
    <div className={`flex items-center gap-2 mb-3`}>
      <h2 className={`text-sm font-bold ${accent}`}>{label}</h2>
      <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full
                        text-[10px] font-bold text-white
                        ${accent.includes('rose') ? 'bg-rose-500' : accent.includes('amber') ? 'bg-amber-500' : 'bg-indigo-500'}`}>
        {count}
      </span>
    </div>
  )
}

/* ── Follow-up card ───────────────────────────────────────────────────────── */
function FollowUpCard({ lead, section, onComplete, completing, onViewLead }) {
  const borderMap = {
    overdue:  'border-l-rose-400',
    today:    'border-l-amber-400',
    upcoming: 'border-l-indigo-300',
  }
  const dateMap = {
    overdue:  'text-rose-600 bg-rose-50 border-rose-200',
    today:    'text-amber-700 bg-amber-50 border-amber-200',
    upcoming: 'text-indigo-700 bg-indigo-50 border-indigo-200',
  }
  const METHOD_ICONS = { Call: '📞', Email: '✉️', WhatsApp: '💬', Meeting: '🤝' }
  const name    = lead.founder_name || lead.company_name || '—'
  const company = lead.founder_name ? (lead.company_name || '') : ''

  return (
    <div className={`bg-white rounded-xl border border-slate-200 border-l-[3px]
                     ${borderMap[section]} p-4 hover:shadow-sm transition-shadow`}>
      <div className="flex items-start justify-between gap-4">
        {/* Left: lead info */}
        <div className="flex-1 min-w-0">
          <button
            onClick={() => onViewLead && onViewLead(lead)}
            className="text-sm font-semibold text-slate-800 hover:text-indigo-700
                       transition-colors text-left truncate block max-w-full"
          >
            {name}
          </button>
          {company && <p className="text-xs text-slate-400 truncate mt-0.5">{company}</p>}

          <div className="flex flex-wrap items-center gap-2 mt-2">
            {/* Date badge */}
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${dateMap[section]}`}>
              {section === 'overdue' ? `⚠ ${lead.follow_up_date}`
               : section === 'today' ? '📅 Today'
               : lead.follow_up_date}
              {lead.follow_up_time && ` · ${lead.follow_up_time}`}
            </span>

            {/* Method */}
            {lead.follow_up_method && (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full
                               bg-slate-50 border border-slate-200 text-slate-600">
                {METHOD_ICONS[lead.follow_up_method] || '•'} {lead.follow_up_method}
              </span>
            )}

            {/* Action */}
            {lead.follow_up_action && (
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full
                               bg-amber-50 border border-amber-200 text-amber-700">
                {lead.follow_up_action}
              </span>
            )}

            {/* Status */}
            <StatusBadge status={lead.status} />

            {/* Category */}
            {lead.category && (
              <span className="text-[10px] px-2 py-0.5 rounded-full
                               bg-indigo-50 text-indigo-600 border border-indigo-100 font-medium">
                {lead.category}
              </span>
            )}
          </div>

          {/* Contact info */}
          {(lead.email || lead.company_number) && (
            <p className="text-xs text-slate-400 mt-1.5 truncate">
              {lead.email || lead.company_number}
            </p>
          )}
        </div>

        {/* Right: actions */}
        {(section === 'overdue' || section === 'today') && (
          <button
            onClick={() => onComplete(lead)}
            disabled={completing}
            className="flex-shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5
                       rounded-lg text-xs font-semibold border border-emerald-200
                       bg-emerald-50 text-emerald-700 hover:bg-emerald-100
                       disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {completing
              ? <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              : <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                </svg>
            }
            Mark Done
          </button>
        )}
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE
   ══════════════════════════════════════════════════════════════════════════════ */
export default function FollowUps() {
  const navigate = useNavigate()
  const [data,       setData]       = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [completing, setCompleting] = useState(null)
  const [refreshTick,setRefreshTick]= useState(0)

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getFollowUps(null)
      .then(setData)
      .catch(err => setError(err.message || 'Failed to load follow-ups.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load, refreshTick])

  const handleComplete = useCallback(async (lead) => {
    setCompleting(lead.id)
    try {
      await markFollowUpCompleted(lead.id, lead.category || null)
      setData(prev => {
        if (!prev) return prev
        const rm = arr => arr.filter(l => l.id !== lead.id)
        const o = rm(prev.overdue  ?? [])
        const t = rm(prev.today    ?? [])
        const u = rm(prev.upcoming ?? [])
        return { ...prev, overdue: o, today: t, upcoming: u,
                 overdue_count: o.length, today_count: t.length, upcoming_count: u.length }
      })
    } catch { load() }
    finally { setCompleting(null) }
  }, [load])

  const handleViewLead = useCallback((lead) => {
    navigate('/', { state: { scrollToLead: lead.id ?? lead._id } })
  }, [navigate])

  const overdue  = data?.overdue  ?? []
  const today    = data?.today    ?? []
  const upcoming = data?.upcoming ?? []
  const dueCount = overdue.length + today.length

  return (
    <Layout
      followUpRefreshTick={refreshTick}
      onOpenFollowUps={() => setRefreshTick(t => t + 1)}
      onNavigateToLead={handleViewLead}
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Page header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between mb-7">
          <div>
            <h1 className="text-xl font-bold text-slate-900">Follow-ups</h1>
            <p className="text-sm text-slate-500 mt-1">
              {loading ? 'Loading…'
                : dueCount > 0 ? `${dueCount} need attention`
                : 'No urgent follow-ups right now'}
            </p>
          </div>
          <button onClick={() => setRefreshTick(t => t + 1)} disabled={loading}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold
                       border border-slate-200 bg-white text-slate-600 hover:bg-slate-50
                       disabled:opacity-40 transition-colors">
            <svg className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}
                 fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
            </svg>
            Refresh
          </button>
        </div>

        {/* ── Loading ──────────────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center justify-center py-20">
            <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
          </div>
        )}

        {/* ── Error ────────────────────────────────────────────────────── */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-sm text-rose-700 mb-4">
            {error}
          </div>
        )}

        {/* ── Empty state ───────────────────────────────────────────────── */}
        {!loading && !error && overdue.length === 0 && today.length === 0 && upcoming.length === 0 && (
          <div className="text-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-indigo-50 flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
              </svg>
            </div>
            <p className="text-base font-semibold text-slate-700">No follow-ups scheduled</p>
            <p className="text-sm text-slate-400 mt-1.5">
              Open a lead's details and set a follow-up date to see it here.
            </p>
          </div>
        )}

        {/* ── Overdue ─────────────────────────────────────────────────── */}
        {!loading && overdue.length > 0 && (
          <div className="mb-7">
            <SectionHeader label="Overdue" count={overdue.length} accent="text-rose-600" />
            <div className="space-y-3">
              {overdue.map(l => (
                <FollowUpCard key={l.id} lead={l} section="overdue"
                  onComplete={handleComplete} completing={completing === l.id}
                  onViewLead={handleViewLead} />
              ))}
            </div>
          </div>
        )}

        {/* ── Due Today ───────────────────────────────────────────────── */}
        {!loading && today.length > 0 && (
          <div className="mb-7">
            <SectionHeader label="Due Today" count={today.length} accent="text-amber-600" />
            <div className="space-y-3">
              {today.map(l => (
                <FollowUpCard key={l.id} lead={l} section="today"
                  onComplete={handleComplete} completing={completing === l.id}
                  onViewLead={handleViewLead} />
              ))}
            </div>
          </div>
        )}

        {/* ── Upcoming ────────────────────────────────────────────────── */}
        {!loading && upcoming.length > 0 && (
          <div className="mb-7">
            <SectionHeader label="Upcoming" count={upcoming.length} accent="text-indigo-600" />
            <div className="space-y-3">
              {upcoming.map(l => (
                <FollowUpCard key={l.id} lead={l} section="upcoming"
                  onComplete={handleComplete} completing={completing === l.id}
                  onViewLead={handleViewLead} />
              ))}
            </div>
          </div>
        )}

        {/* ── Summary footer ──────────────────────────────────────────── */}
        {!loading && (overdue.length + today.length + upcoming.length) > 0 && (
          <div className="pt-4 border-t border-slate-200 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
            {overdue.length  > 0 && <span className="text-rose-600 font-semibold">⚠ {overdue.length} overdue</span>}
            {today.length    > 0 && <span className="text-amber-600 font-semibold">📅 {today.length} today</span>}
            {upcoming.length > 0 && <span>{upcoming.length} upcoming</span>}
          </div>
        )}
      </div>
    </Layout>
  )
}
