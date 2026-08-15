/**
 * NotificationBell
 *
 * Shows a bell icon in the header with a badge count of follow-ups due today
 * plus overdue. Clicking it opens a compact dropdown panel with three sections:
 *   • Overdue
 *   • Due Today
 *   • Upcoming
 *
 * Each item has a "Mark as Completed" action that removes it without deleting
 * the lead.
 *
 * Props:
 *   category       – string | null  – filter to one category (or all)
 *   refreshTick    – number         – bump from parent to force re-fetch
 *   onOpenPanel    – () => void     – open the full FollowUpsPanel modal
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { getFollowUps, markFollowUpCompleted } from '../services/api'

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const map = {
    interested:     'bg-emerald-100 text-emerald-700',
    not_interested: 'bg-rose-100 text-rose-700',
    new:            'bg-slate-100 text-slate-600',
  }
  const labels = { interested: 'Interested', not_interested: 'Not Interested', new: 'New' }
  const cls = map[status] || map.new
  const label = labels[status] || status || 'New'
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${cls}`}>
      {label}
    </span>
  )
}

// ── Single notification row ───────────────────────────────────────────────────
function NotifRow({ lead, section, onComplete, completing }) {
  const name    = lead.founder_name || lead.company_name || '—'
  const company = lead.founder_name ? (lead.company_name || '') : ''
  const contact = lead.email || lead.company_number || lead.founder_number || ''

  const sectionStyles = {
    overdue: 'border-l-2 border-rose-400',
    today:   'border-l-2 border-amber-400',
    upcoming:'border-l-2 border-indigo-300',
  }

  return (
    <div className={`px-3 py-2.5 hover:bg-slate-50 transition-colors ${sectionStyles[section] || ''}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {/* Name + company */}
          <p className="text-xs font-semibold text-slate-800 truncate leading-tight">{name}</p>
          {company && (
            <p className="text-[10px] text-slate-400 truncate leading-tight">{company}</p>
          )}
          {/* Contact + status */}
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {contact && (
              <span className="text-[10px] text-slate-500 truncate max-w-[140px]">{contact}</span>
            )}
            <StatusBadge status={lead.status} />
          </div>
          {/* Date */}
          <p className="text-[10px] text-slate-400 mt-0.5">
            {section === 'overdue'
              ? <span className="text-rose-500 font-semibold">⚠ Overdue · {lead.follow_up_date}</span>
              : section === 'today'
                ? <span className="text-amber-600 font-semibold">📅 Due Today</span>
                : <span className="text-indigo-500">{lead.follow_up_date}</span>
            }
          </p>
        </div>

        {/* Complete button — only for overdue + today */}
        {(section === 'overdue' || section === 'today') && (
          <button
            onClick={() => onComplete(lead)}
            disabled={completing}
            title="Mark follow-up as completed"
            className="flex-shrink-0 mt-0.5 inline-flex items-center gap-1 px-2 py-1 rounded-md
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
            Done
          </button>
        )}
      </div>
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHeader({ label, count, dotClass, labelClass }) {
  if (count === 0) return null
  return (
    <div className={`px-3 py-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider ${labelClass} bg-slate-50 border-b border-slate-100`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`}/>
      {label} ({count})
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function NotificationBell({ category, refreshTick, onOpenPanel }) {
  const [data,        setData]        = useState(null)
  const [open,        setOpen]        = useState(false)
  const [loading,     setLoading]     = useState(false)
  const [completing,  setCompleting]  = useState(null) // lead id being completed
  const panelRef = useRef(null)

  // ── Fetch follow-ups ────────────────────────────────────────────────────────
  const fetchData = useCallback(() => {
    setLoading(true)
    getFollowUps(category || null)
      .then(setData)
      .catch(() => {}) // silently fail for background polling
      .finally(() => setLoading(false))
  }, [category])

  // Fetch on mount, on category change, and on parent refreshTick
  useEffect(() => { fetchData() }, [fetchData, refreshTick])

  // Polling — re-fetch every 5 minutes while tab is visible
  useEffect(() => {
    const interval = setInterval(() => {
      if (document.visibilityState === 'visible') fetchData()
    }, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [fetchData])

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!open) return
    function handleClick(e) {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  // ── Mark complete ───────────────────────────────────────────────────────────
  const handleComplete = useCallback(async (lead) => {
    setCompleting(lead.id)
    try {
      await markFollowUpCompleted(lead.id, lead.category || category || null)
      // Optimistically remove from local data
      setData(prev => {
        if (!prev) return prev
        const remove = (arr) => arr.filter(l => l.id !== lead.id)
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
      // Refetch to sync
      fetchData()
    } finally {
      setCompleting(null)
    }
  }, [category, fetchData])

  // ── Derived values ──────────────────────────────────────────────────────────
  const overdueLeads  = data?.overdue   ?? []
  const todayLeads    = data?.today     ?? []
  const upcomingLeads = data?.upcoming  ?? []
  const dueCount      = (data?.due_count) ?? 0
  const hasAny        = overdueLeads.length + todayLeads.length + upcomingLeads.length > 0

  return (
    <div className="relative" ref={panelRef}>

      {/* Bell button */}
      <button
        onClick={() => setOpen(o => !o)}
        title={dueCount > 0 ? `${dueCount} follow-up${dueCount !== 1 ? 's' : ''} need attention` : 'No follow-ups due'}
        className={`
          relative inline-flex items-center justify-center
          h-8 w-8 rounded-lg border text-xs font-semibold shadow-sm
          transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-rose-400
          ${dueCount > 0
            ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
            : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:border-slate-300'
          }
        `}
      >
        {/* Bell icon */}
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
        </svg>

        {/* Badge */}
        {dueCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1
                           flex items-center justify-center
                           rounded-full bg-rose-500 text-white text-[9px] font-bold
                           leading-none shadow-sm">
            {dueCount > 99 ? '99+' : dueCount}
          </span>
        )}

        {/* Subtle pulse ring when there are overdue items */}
        {overdueLeads.length > 0 && (
          <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full
                           bg-rose-400 opacity-75 animate-ping" />
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 bg-white rounded-xl
                        shadow-2xl border border-slate-200 overflow-hidden">

          {/* Panel header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
              </svg>
              <span className="text-sm font-bold text-slate-800">Follow-ups</span>
              {loading && (
                <svg className="w-3.5 h-3.5 animate-spin text-slate-400 ml-1" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setOpen(false); onOpenPanel?.() }}
                className="text-[10px] font-semibold text-indigo-600 hover:text-indigo-800
                           hover:underline transition-colors"
              >
                View All
              </button>
              <button
                onClick={fetchData}
                disabled={loading}
                title="Refresh"
                className="w-5 h-5 flex items-center justify-center rounded
                           text-slate-400 hover:text-slate-600 disabled:opacity-40"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                </svg>
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="max-h-[420px] overflow-y-auto">
            {!hasAny && !loading && (
              <div className="py-10 flex flex-col items-center gap-2 text-slate-400">
                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                </svg>
                <p className="text-xs font-medium">No follow-ups due</p>
              </div>
            )}

            {/* Overdue section */}
            {overdueLeads.length > 0 && (
              <>
                <SectionHeader
                  label="Overdue"
                  count={overdueLeads.length}
                  dotClass="bg-rose-500"
                  labelClass="text-rose-600"
                />
                <div className="divide-y divide-slate-50">
                  {overdueLeads.map(lead => (
                    <NotifRow
                      key={lead.id}
                      lead={lead}
                      section="overdue"
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                    />
                  ))}
                </div>
              </>
            )}

            {/* Due Today section */}
            {todayLeads.length > 0 && (
              <>
                <SectionHeader
                  label="Due Today"
                  count={todayLeads.length}
                  dotClass="bg-amber-400"
                  labelClass="text-amber-600"
                />
                <div className="divide-y divide-slate-50">
                  {todayLeads.map(lead => (
                    <NotifRow
                      key={lead.id}
                      lead={lead}
                      section="today"
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                    />
                  ))}
                </div>
              </>
            )}

            {/* Upcoming section */}
            {upcomingLeads.length > 0 && (
              <>
                <SectionHeader
                  label="Upcoming"
                  count={upcomingLeads.length}
                  dotClass="bg-indigo-400"
                  labelClass="text-indigo-600"
                />
                <div className="divide-y divide-slate-50">
                  {upcomingLeads.map(lead => (
                    <NotifRow
                      key={lead.id}
                      lead={lead}
                      section="upcoming"
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                    />
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Footer */}
          {hasAny && (
            <div className="px-4 py-2.5 border-t border-slate-100 bg-slate-50
                            flex items-center justify-between">
              <span className="text-[10px] text-slate-400">
                {overdueLeads.length > 0 && `${overdueLeads.length} overdue · `}
                {todayLeads.length} today · {upcomingLeads.length} upcoming
              </span>
              <button
                onClick={() => { setOpen(false); onOpenPanel?.() }}
                className="text-[10px] font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                Open full panel →
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
