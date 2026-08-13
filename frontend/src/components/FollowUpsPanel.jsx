import { useState, useEffect } from 'react'
import { getFollowUps } from '../services/api'

function FollowUpRow({ lead, label }) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3
                    rounded-xl border border-slate-100 bg-white hover:bg-slate-50
                    transition-colors">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-slate-800 truncate">
          {lead.company_name || '—'}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          {lead.email && (
            <span className="text-xs text-slate-400 truncate">{lead.email}</span>
          )}
          {lead.category && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-50
                             text-indigo-600 font-medium flex-shrink-0">
              {lead.category}
            </span>
          )}
        </div>
      </div>
      <div className="flex-shrink-0 text-right">
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${
          label === 'Today'
            ? 'bg-rose-100 text-rose-700'
            : 'bg-indigo-50 text-indigo-700'
        }`}>
          {label === 'Today' ? '📅 Today' : lead.follow_up_date}
        </span>
      </div>
    </div>
  )
}

export default function FollowUpsPanel({ category, onClose }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState('')

  useEffect(() => {
    setLoading(true)
    getFollowUps(category || null)
      .then(setData)
      .catch((err) => setError(err.message || 'Failed to load follow-ups.'))
      .finally(() => setLoading(false))
  }, [category])

  const todayLeads    = data?.today    ?? []
  const upcomingLeads = data?.upcoming ?? []
  const hasAny = todayLeads.length > 0 || upcomingLeads.length > 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center
                 bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh]
                      flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
            </svg>
            <h2 className="text-base font-bold text-slate-800">Follow-ups</h2>
            {data && (
              <span className="text-xs text-slate-400">
                {data.today_count + data.upcoming_count} total
              </span>
            )}
          </div>
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

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <svg className="w-6 h-6 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}

          {error && (
            <p className="text-sm text-rose-600 text-center py-4">{error}</p>
          )}

          {!loading && !error && !hasAny && (
            <div className="text-center py-12">
              <p className="text-2xl mb-2">📅</p>
              <p className="text-sm text-slate-500 font-medium">No follow-ups scheduled</p>
              <p className="text-xs text-slate-400 mt-1">
                Open a lead's details and set a follow-up date.
              </p>
            </div>
          )}

          {/* Today */}
          {todayLeads.length > 0 && (
            <section>
              <h3 className="text-xs font-bold text-rose-600 uppercase tracking-widest mb-2.5
                             flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 flex-shrink-0"/>
                Today ({todayLeads.length})
              </h3>
              <div className="space-y-2">
                {todayLeads.map((l) => (
                  <FollowUpRow key={l.id} lead={l} label="Today" />
                ))}
              </div>
            </section>
          )}

          {/* Upcoming */}
          {upcomingLeads.length > 0 && (
            <section>
              <h3 className="text-xs font-bold text-indigo-600 uppercase tracking-widest mb-2.5
                             flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 flex-shrink-0"/>
                Upcoming ({upcomingLeads.length})
              </h3>
              <div className="space-y-2">
                {upcomingLeads.map((l) => (
                  <FollowUpRow key={l.id} lead={l} label="Upcoming" />
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
