/**
 * NotificationBell
 *
 * Shows a bell icon in the header with a badge count of follow-ups that need
 * attention:
 *   🔴 Overdue   — follow_up_date has passed (+ time if set)
 *   🟠 Due Today — follow_up_date is today
 *   🟡 Upcoming  — follow_up_date/time is within the next 24 hours
 *
 * Features:
 *   • Displays company name, date, time, method, next action
 *   • Mark as Read per notification (persisted in localStorage)
 *   • Clicking a notification navigates to that lead in the CRM
 *   • Badge counts only unread notifications
 *   • Polls every 5 minutes while the tab is visible
 *
 * Props:
 *   category       – string | null  – filter to one category (or all)
 *   refreshTick    – number         – bump from parent to force re-fetch
 *   onOpenPanel    – () => void     – open the full FollowUpsPanel modal
 *   onNavigateLead – (lead) => void – called when user clicks a notification row
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { getFollowUps, markFollowUpCompleted } from '../services/api'

// ── localStorage helpers for "read" state ─────────────────────────────────────
const LS_KEY = 'crm_followup_read_ids'

function getReadIds() {
  try { return new Set(JSON.parse(localStorage.getItem(LS_KEY) || '[]')) }
  catch { return new Set() }
}
function saveReadIds(set) {
  try { localStorage.setItem(LS_KEY, JSON.stringify([...set])) } catch {}
}
function markRead(id) {
  const s = getReadIds(); s.add(id); saveReadIds(s)
}
function markAllRead(ids) {
  const s = getReadIds(); ids.forEach(id => s.add(id)); saveReadIds(s)
}

// ── Time helpers ──────────────────────────────────────────────────────────────

/** Parse "YYYY-MM-DD" + optional "HH:MM" into a local Date */
function parseLocalDateTime(date, time) {
  if (!date) return null
  const str = time ? `${date}T${time}:00` : `${date}T00:00:00`
  return new Date(str)
}

/** Format "HH:MM" string → "4:00 PM" in user locale */
function fmtTime(time) {
  if (!time) return null
  try {
    const [h, m] = time.split(':').map(Number)
    return new Intl.DateTimeFormat('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true }).format(new Date(2000, 0, 1, h, m))
  } catch { return time }
}

/** Returns true if a lead's follow-up is within the next 24 hours (future only) */
function isWithin24h(lead) {
  const dt = parseLocalDateTime(lead.follow_up_date, lead.follow_up_time)
  if (!dt) return false
  const now = Date.now()
  const diff = dt.getTime() - now
  return diff > 0 && diff <= 24 * 60 * 60 * 1000
}

/** Returns true if a lead's follow-up datetime has passed */
function isOverdueDatetime(lead) {
  // follow_up_date is always set if we're in overdue bucket, but check time too
  if (!lead.follow_up_time) return true  // no time → whole date is overdue
  const dt = parseLocalDateTime(lead.follow_up_date, lead.follow_up_time)
  return dt ? dt.getTime() < Date.now() : true
}

// ── Urgency config ────────────────────────────────────────────────────────────
const URGENCY = {
  overdue: { emoji: '🔴', label: 'Overdue',   dot: 'bg-rose-500',   text: 'text-rose-600',   border: 'border-l-rose-400',   bg: 'hover:bg-rose-50/60' },
  today:   { emoji: '🟠', label: 'Due Today', dot: 'bg-amber-400',  text: 'text-amber-600',  border: 'border-l-amber-400',  bg: 'hover:bg-amber-50/60' },
  upcoming:{ emoji: '🟡', label: 'Upcoming',  dot: 'bg-yellow-400', text: 'text-yellow-600', border: 'border-l-yellow-300', bg: 'hover:bg-yellow-50/40' },
}

const METHOD_ICONS = { Call: '📞', Email: '✉️', WhatsApp: '💬', Meeting: '🤝' }

// ── Single notification row ───────────────────────────────────────────────────
function NotifRow({ lead, section, isRead, onRead, onComplete, completing, onNavigate }) {
  const u = URGENCY[section]
  const company = lead.company_name || '—'
  const timeStr = fmtTime(lead.follow_up_time)
  const method  = lead.follow_up_method || null
  const action  = lead.follow_up_action || null

  // Build the date label
  let dateLabel
  if (section === 'overdue') {
    dateLabel = <span className="text-rose-500 font-semibold">⚠ Overdue · {lead.follow_up_date}{timeStr ? `, ${timeStr}` : ''}</span>
  } else if (section === 'today') {
    dateLabel = <span className="text-amber-600 font-semibold">Today{timeStr ? `, ${timeStr}` : ''}</span>
  } else {
    dateLabel = <span className="text-yellow-600">{lead.follow_up_date}{timeStr ? `, ${timeStr}` : ''}</span>
  }

  const handleRowClick = () => {
    onRead(lead.id)
    onNavigate?.(lead)
  }

  return (
    <div
      className={`px-3 py-2.5 border-l-2 ${u.border} transition-colors cursor-pointer
                  ${isRead ? 'opacity-60' : ''} ${u.bg}`}
      onClick={handleRowClick}
      title="Click to open this lead in the CRM"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          {/* Urgency + company */}
          <p className="text-xs font-bold text-slate-800 truncate leading-tight flex items-center gap-1">
            <span>{u.emoji}</span>
            <span className="truncate">{company}</span>
            {isRead && <span className="text-[9px] text-slate-400 font-normal flex-shrink-0">(read)</span>}
          </p>

          {/* Date/time row */}
          <p className="text-[10px] mt-0.5">{dateLabel}</p>

          {/* Method + Action */}
          {(method || action) && (
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              {method && (
                <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full
                                 bg-indigo-50 border border-indigo-200 text-indigo-700 text-[9px] font-semibold">
                  {METHOD_ICONS[method] || '•'} {method}
                </span>
              )}
              {action && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded-full
                                 bg-amber-50 border border-amber-200 text-amber-700 text-[9px] font-semibold">
                  {action}
                </span>
              )}
            </div>
          )}
        </div>

        {/* Right side buttons */}
        <div className="flex flex-col items-end gap-1 flex-shrink-0" onClick={e => e.stopPropagation()}>
          {/* Mark Read / Unread */}
          <button
            onClick={() => onRead(lead.id)}
            title={isRead ? 'Mark as unread' : 'Mark as read'}
            className="text-[9px] text-slate-400 hover:text-indigo-600 transition-colors underline"
          >
            {isRead ? 'Unread' : 'Read'}
          </button>

          {/* Complete button — overdue + today only */}
          {(section === 'overdue' || section === 'today') && (
            <button
              onClick={() => onComplete(lead)}
              disabled={completing}
              title="Mark follow-up as completed"
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md
                         text-[9px] font-semibold
                         bg-emerald-50 text-emerald-700 border border-emerald-200
                         hover:bg-emerald-100 disabled:opacity-50 transition-colors"
            >
              {completing
                ? <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                : <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                  </svg>
              }
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHeader({ label, count, dotClass, labelClass }) {
  if (count === 0) return null
  return (
    <div className={`px-3 py-1.5 flex items-center gap-1.5 text-[10px] font-bold uppercase
                     tracking-wider ${labelClass} bg-slate-50 border-b border-slate-100`}>
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${dotClass}`}/>
      {label} ({count})
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function NotificationBell({ category, refreshTick, onOpenPanel, onNavigateLead }) {
  const [data,       setData]       = useState(null)
  const [open,       setOpen]       = useState(false)
  const [loading,    setLoading]    = useState(false)
  const [completing, setCompleting] = useState(null)
  const [readIds,    setReadIds]    = useState(() => getReadIds())
  const panelRef = useRef(null)

  // ── Fetch follow-ups ────────────────────────────────────────────────────────
  const fetchData = useCallback(() => {
    setLoading(true)
    getFollowUps(category || null)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [category])

  useEffect(() => { fetchData() }, [fetchData, refreshTick])

  // Poll every 5 minutes while tab is visible
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === 'visible') fetchData()
    }, 5 * 60 * 1000)
    return () => clearInterval(id)
  }, [fetchData])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // ── Derived lists ───────────────────────────────────────────────────────────
  const overdueLeads  = data?.overdue   ?? []
  const todayLeads    = data?.today     ?? []

  // Upcoming: filter backend's 30-day list down to next 24 hours only
  const upcomingLeads = useMemo(
    () => (data?.upcoming ?? []).filter(isWithin24h),
    [data]
  )

  // All notification IDs
  const allIds = useMemo(
    () => [...overdueLeads, ...todayLeads, ...upcomingLeads].map(l => l.id),
    [overdueLeads, todayLeads, upcomingLeads]
  )

  // Unread count = items not yet in readIds
  const unreadCount = useMemo(
    () => allIds.filter(id => !readIds.has(id)).length,
    [allIds, readIds]
  )

  const hasAny = overdueLeads.length + todayLeads.length + upcomingLeads.length > 0

  // ── Read/unread toggle ──────────────────────────────────────────────────────
  const handleToggleRead = useCallback((id) => {
    setReadIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) } else { next.add(id) }
      saveReadIds(next)
      return next
    })
  }, [])

  const handleMarkAllRead = useCallback(() => {
    setReadIds(prev => {
      const next = new Set(prev)
      allIds.forEach(id => next.add(id))
      saveReadIds(next)
      return next
    })
  }, [allIds])

  // ── Mark complete ───────────────────────────────────────────────────────────
  const handleComplete = useCallback(async (lead) => {
    setCompleting(lead.id)
    try {
      await markFollowUpCompleted(lead.id, lead.category || category || null)
      // Remove from read state too
      setReadIds(prev => { const n = new Set(prev); n.delete(lead.id); saveReadIds(n); return n })
      // Optimistically remove from data
      setData(prev => {
        if (!prev) return prev
        const rm = arr => arr.filter(l => l.id !== lead.id)
        const o = rm(prev.overdue  ?? [])
        const t = rm(prev.today    ?? [])
        const u = rm(prev.upcoming ?? [])
        return { ...prev, overdue: o, today: t, upcoming: u,
                 overdue_count: o.length, today_count: t.length,
                 upcoming_count: u.length, due_count: o.length + t.length }
      })
    } catch { fetchData() }
    finally { setCompleting(null) }
  }, [category, fetchData])

  // ── Navigate to lead ────────────────────────────────────────────────────────
  const handleNavigate = useCallback((lead) => {
    setOpen(false)
    onNavigateLead?.(lead)
  }, [onNavigateLead])

  // ── Open bell: mark all visible as read ────────────────────────────────────
  const handleBellClick = () => {
    setOpen(o => !o)
  }

  return (
    <div className="relative" ref={panelRef}>

      {/* ── Bell button ── */}
      <button
        onClick={handleBellClick}
        title={unreadCount > 0
          ? `${unreadCount} unread follow-up reminder${unreadCount !== 1 ? 's' : ''}`
          : 'No unread follow-up reminders'}
        className={`
          relative inline-flex items-center justify-center
          h-8 w-8 rounded-lg border text-xs font-semibold shadow-sm
          transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-rose-400
          ${unreadCount > 0
            ? 'border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
            : 'border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:border-slate-300'
          }
        `}
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
        </svg>

        {/* Unread badge */}
        {unreadCount > 0 && (
          <span className="absolute -top-1.5 -right-1.5 min-w-[16px] h-4 px-1
                           flex items-center justify-center
                           rounded-full bg-rose-500 text-white text-[9px] font-bold
                           leading-none shadow-sm">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}

        {/* Pulse ring for overdue */}
        {overdueLeads.some(l => !readIds.has(l.id)) && (
          <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full
                           bg-rose-400 opacity-75 animate-ping pointer-events-none" />
        )}
      </button>

      {/* ── Dropdown panel ── */}
      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 bg-white rounded-xl
                        shadow-2xl border border-slate-200 overflow-hidden">

          {/* Panel header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <div className="flex items-center gap-2">
              <svg className="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
              </svg>
              <span className="text-sm font-bold text-slate-800">Follow-up Reminders</span>
              {loading && (
                <svg className="w-3.5 h-3.5 animate-spin text-slate-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* Mark all read */}
              {hasAny && unreadCount > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="text-[10px] font-semibold text-slate-500 hover:text-indigo-600
                             hover:underline transition-colors"
                  title="Mark all as read"
                >
                  Mark all read
                </button>
              )}
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
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0
                       0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
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
                <p className="text-xs font-medium">No follow-up reminders</p>
              </div>
            )}

            {/* 🔴 Overdue */}
            {overdueLeads.length > 0 && (
              <>
                <SectionHeader label="🔴 Overdue" count={overdueLeads.length}
                  dotClass="bg-rose-500" labelClass="text-rose-600" />
                <div className="divide-y divide-slate-50">
                  {overdueLeads.map(lead => (
                    <NotifRow key={lead.id} lead={lead} section="overdue"
                      isRead={readIds.has(lead.id)}
                      onRead={handleToggleRead}
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                      onNavigate={handleNavigate}
                    />
                  ))}
                </div>
              </>
            )}

            {/* 🟠 Due Today */}
            {todayLeads.length > 0 && (
              <>
                <SectionHeader label="🟠 Due Today" count={todayLeads.length}
                  dotClass="bg-amber-400" labelClass="text-amber-600" />
                <div className="divide-y divide-slate-50">
                  {todayLeads.map(lead => (
                    <NotifRow key={lead.id} lead={lead} section="today"
                      isRead={readIds.has(lead.id)}
                      onRead={handleToggleRead}
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                      onNavigate={handleNavigate}
                    />
                  ))}
                </div>
              </>
            )}

            {/* 🟡 Upcoming (next 24 h) */}
            {upcomingLeads.length > 0 && (
              <>
                <SectionHeader label="🟡 Upcoming (24 h)" count={upcomingLeads.length}
                  dotClass="bg-yellow-400" labelClass="text-yellow-600" />
                <div className="divide-y divide-slate-50">
                  {upcomingLeads.map(lead => (
                    <NotifRow key={lead.id} lead={lead} section="upcoming"
                      isRead={readIds.has(lead.id)}
                      onRead={handleToggleRead}
                      onComplete={handleComplete}
                      completing={completing === lead.id}
                      onNavigate={handleNavigate}
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
                {todayLeads.length} today · {upcomingLeads.length} in 24h
                {unreadCount > 0 && ` · ${unreadCount} unread`}
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
