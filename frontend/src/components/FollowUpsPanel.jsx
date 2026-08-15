/**
 * FollowUpsPanel
 *
 * Full-screen modal showing three sections:
 *   1. Overdue  — follow_up_date < today, status != not_interested
 *   2. Due Today
 *   3. Upcoming
 *
 * Each overdue/today row has a "Mark as Completed" button.
 * After completion the row is removed without deleting the lead.
 *
 * Props:
 *   category – string | null
 *   onClose  – () => void
 */

import { useState, useEffect, useCallback } from 'react'
import { getFollowUps, markFollowUpCompleted } from '../services/api'

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    interested:     'bg-emerald-100 text-emerald-700 border-emerald-200',
    not_interested: 'bg-rose-100 text-rose-700 border-rose-200',
    new:            'bg-slate-100 text-slate-600 border-slate-200',
  }
  const labels = { interested: 'Interested', not_interested: 'Not Interested', new: 'New' }
  const cls   = map[status] || map.new
  const label = labels[status] || status || 'New'
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${cls}`}>
      {label}
    </span>
  )
}

// ── Single follow-up row ──────────────────────────────────────────────────────
function FollowUpRow({ lead, section, onComplete, completing }) {
  const name    = lead.founder_name || lead.company_name || '—'
  const company = lead.founder_name ? (lead.company_name || '') : ''
  const phone   = lead.company_number || lead.founder_number || ''

  // Section-specific left-border colour
  const borderCls = {
    overdue: 'border-l-[3px] border-l-rose-400',
    today:   'border-l-[3px] border-l-amber-400',
    upcoming:'border-l-[3px] border-l-indigo-300',
  }[section] || ''

  return (
    <div className={`flex items-start justify-between gap-3 px-4 py-3
                     rounded-xl border border-slate-100 bg-white hover:bg-slate-50
                     transition-colors ${borderCls}`}>
      {/* Lead info */}
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-slate-800 truncate">{name}</p>
        {company && (
          <p className="text-xs text-slate-400 truncate">{company}</p>
        )}
        <div className="flex flex-wrap items-center gap-2 mt-1">
          {lead.email && (
            <span className="text-xs text-slate-400 truncate max-w-[180px]">{lead.email}</span>
          )}
          {phone && !lead.email && (
            <span className="text-xs text-slate-400">{phone}</span>
          )}
          {lead.category && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full
                             bg-indigo-50 text-indigo-600 font-medium flex-shrink-0">
              {lead.category}
            </span>
          )}
          <StatusBadge status={lead.status} />
        </div>
      </div>

      {/* Date + Complete action */}
      <div className="flex-shrink-0 flex flex-col items-end gap-1.5">
        {/* Date badge */}
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${
          section === 'overdue'
            ? 'bg-rose-100 text-rose-700'
            : section === 'today'
              ? 'bg-amber-100 text-amber-700'
              : 'bg-indigo-50 text-indigo-700'
        }`}>
          {section === 'overdue' ? `⚠ ${lead.follow_up_date}`
           : section === 'today' ? '📅 Today'
           : lead.follow_up_date}
        </span>

        {/* Mark as Completed button — only for overdue + today */}
        {(section === 'overdue' || section === 'today') && (
          <button
            onClick={() => onComplete(lead)}
            disabled={completing}
            title="Mark follow-up as completed"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md
                       text-[10px] font-semibold
                       bg-emerald-50 text-emerald-700 border border-emerald-200
                       hover:bg-emerald-100 disabled:opacity-50 transition-colors"
          >
            {completing ? (
              <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            ) : (
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
              </svg>
            )}
            Mark Done
          </button>
        )}
      </div>
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHeading({ emoji, label, count, colorClass }) {
  return (
    <h3 className={`text-xs font-bold uppercase tracking-widest mb-2.5
                    flex items-center gap-1.5 ${colorClass}`}>
      <span>{emoji}</span>
      {label} ({count})
    </h3>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function FollowUpsPanel({ category, onClose }) {
  const [data,       setData]       = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [completing, setCompleting] = useState(null) // lead.id being completed

  const load = useCallback(() => {
    setLoading(true)
    setError('')
    getFollowUps(category || null)
      .then(setData)
      .catch((err) => setError(err.message || 'Failed to load follow-ups.'))
      .finally(() => setLoading(false))
  }, [category])

  useEffect(() => { load() }, [load])

  // Mark a follow-up as completed
  const handleComplete = useCallback(async (lead) => {
    setCompleting(lead.id)
    try {
      await markFollowUpCompleted(lead.id, lead.category || category || null)
      // Optimistically remove from local lists
      setData(prev => {
        if (!prev) return prev
        const remove = arr => arr.filter(l => l.id !== lead.id)
        const nextOverdue  = remove(prev.overdue  ?? [])
        const nextToday    = remove(prev.today    ?? [])
        const nextUpcoming = remove(prev.upcoming ?? [])
        return {
          ...prev,
          overdue:        nextOverdue,
          today:          nextToday,
          upcoming:       nextUpcoming,
          overdue_count:  nextOverdue.length,
          today_count:    nextToday.length,
          upcoming_count: nextUpcoming.length,
          due_count:      nextOverdue.length + nextToday.length,
        }
      })
    } catch {
      load() // re-fetch to stay in sync
    } finally {
      setCompleting(null)
    }
  }, [category, load])

  const overdueLeads  = data?.overdue   ?? []
  const todayLeads    = data?.today     ?? []
  const upcomingLeads = data?.upcoming  ?? []
  const total = overdueLeads.length + todayLeads.length + upcomingLeads.length

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center
                 bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[88vh]
                      flex flex-col overflow-hidden">

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
            <h2 className="text-base font-bold text-slate-800">Follow-ups</h2>
            {data && !loading && (
              <span className="text-xs text-slate-400">
                {total} scheduled
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              title="Refresh"
              className="w-7 h-7 flex items-center justify-center rounded-lg
                         text-slate-400 hover:text-slate-600 hover:bg-slate-100
                         disabled:opacity-40 transition-colors"
            >
              <svg className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}
                   fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
              </svg>
            </button>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full flex items-center justify-center
                         text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>

        {/* ── Content ── */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">

          {/* Loading spinner */}
          {loading && (
            <div className="flex items-center justify-center py-12">
              <svg className="w-6 h-6 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}

          {/* Error */}
          {error && (
            <p className="text-sm text-rose-600 text-center py-4">{error}</p>
          )}

          {/* Empty state */}
          {!loading && !error && total === 0 && (
            <div className="text-center py-12">
              <p className="text-3xl mb-3">📅</p>
              <p className="text-sm text-slate-500 font-medium">No follow-ups scheduled</p>
              <p className="text-xs text-slate-400 mt-1">
                Open a lead's details and set a follow-up date to see it here.
              </p>
            </div>
          )}

          {/* ── Overdue section ── */}
          {overdueLeads.length > 0 && (
            <section>
              <SectionHeading
                emoji="⚠"
                label="Overdue"
                count={overdueLeads.length}
                colorClass="text-rose-600"
              />
              <div className="space-y-2">
                {overdueLeads.map(l => (
                  <FollowUpRow
                    key={l.id}
                    lead={l}
                    section="overdue"
                    onComplete={handleComplete}
                    completing={completing === l.id}
                  />
                ))}
              </div>
            </section>
          )}

          {/* ── Due Today section ── */}
          {todayLeads.length > 0 && (
            <section>
              <SectionHeading
                emoji="📅"
                label="Due Today"
                count={todayLeads.length}
                colorClass="text-amber-600"
              />
              <div className="space-y-2">
                {todayLeads.map(l => (
                  <FollowUpRow
                    key={l.id}
                    lead={l}
                    section="today"
                    onComplete={handleComplete}
                    completing={completing === l.id}
                  />
                ))}
              </div>
            </section>
          )}

          {/* ── Upcoming section ── */}
          {upcomingLeads.length > 0 && (
            <section>
              <SectionHeading
                emoji="🗓"
                label="Upcoming"
                count={upcomingLeads.length}
                colorClass="text-indigo-600"
              />
              <div className="space-y-2">
                {upcomingLeads.map(l => (
                  <FollowUpRow
                    key={l.id}
                    lead={l}
                    section="upcoming"
                    onComplete={handleComplete}
                    completing={completing === l.id}
                  />
                ))}
              </div>
            </section>
          )}
        </div>

        {/* ── Footer summary ── */}
        {!loading && total > 0 && (
          <div className="px-6 py-3 border-t border-slate-100 bg-slate-50
                          flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
            {overdueLeads.length > 0 && (
              <span className="text-rose-600 font-semibold">
                ⚠ {overdueLeads.length} overdue
              </span>
            )}
            {todayLeads.length > 0 && (
              <span className="text-amber-600 font-semibold">
                📅 {todayLeads.length} due today
              </span>
            )}
            <span>{upcomingLeads.length} upcoming</span>
          </div>
        )}
      </div>
    </div>
  )
}
