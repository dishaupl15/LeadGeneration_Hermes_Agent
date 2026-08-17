/**
 * FollowUpModal.jsx
 *
 * Compact modal for setting / editing a lead's follow-up.
 * Fields:
 *   📅 Date        — date picker
 *   ⏰ Time        — time picker
 *   Method        — Call | Email | WhatsApp | Meeting
 *   Next Action   — predefined options + Other
 *
 * Props:
 *   lead          — the lead object (needs id/_id and category)
 *   onClose()     — close without saving
 *   onSaved(lead) — called with the updated lead after successful save
 */

import { useState } from 'react'
import { updateLeadFollowUp } from '../services/api'

const METHODS = ['Call', 'Email', 'WhatsApp', 'Meeting']

const NEXT_ACTIONS = [
  'Call client',
  'Send proposal',
  'Send pricing',
  'Demo',
  'Meeting',
  'Send website sample',
  'Other',
]

const METHOD_ICONS = {
  Call:      '📞',
  Email:     '✉️',
  WhatsApp:  '💬',
  Meeting:   '🤝',
}

export default function FollowUpModal({ lead, onClose, onSaved }) {
  const existing = {
    date:   lead.follow_up_date   || '',
    time:   lead.follow_up_time   || '',
    method: lead.follow_up_method || '',
    action: lead.follow_up_action || '',
  }

  const [date,   setDate]   = useState(existing.date)
  const [time,   setTime]   = useState(existing.time)
  const [method, setMethod] = useState(existing.method)
  const [action, setAction] = useState(existing.action)
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState('')

  const leadId   = lead.id ?? lead._id
  const category = lead.category ?? null

  const handleSave = async () => {
    if (!date) { setError('Please select a follow-up date.'); return }
    if (!method) { setError('Please select a follow-up method.'); return }
    if (!action) { setError('Please select a next action.'); return }
    setSaving(true)
    setError('')
    try {
      const res = await updateLeadFollowUp(leadId, date, category, time || null, method, action)
      onSaved(res.lead)
    } catch (err) {
      setError(err.message || 'Failed to save follow-up.')
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    setSaving(true)
    setError('')
    try {
      const res = await updateLeadFollowUp(leadId, null, category, null, null, null)
      onSaved(res.lead)
    } catch (err) {
      setError(err.message || 'Failed to clear follow-up.')
    } finally {
      setSaving(false)
    }
  }

  const hasExisting = !!(existing.date || existing.method || existing.action)

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center
                 bg-black/50 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-sm
                   flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-5 py-4
                        border-b border-slate-100 bg-indigo-50/60">
          <div>
            <h3 className="text-sm font-bold text-slate-800 flex items-center gap-1.5">
              <span>📅</span>
              {hasExisting ? 'Edit Follow-up' : 'Add Follow-up'}
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5 truncate max-w-[220px]">
              {lead.company_name || '—'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-full flex items-center justify-center
                       text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        {/* Form */}
        <div className="px-5 py-4 space-y-4">

          {/* Date + Time row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-[11px] font-semibold text-slate-500
                                uppercase tracking-wide mb-1.5">
                📅 Date <span className="text-rose-500">*</span>
              </label>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                min={new Date().toISOString().split('T')[0]}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm
                           text-slate-700 bg-white focus:outline-none focus:ring-2
                           focus:ring-indigo-400 focus:border-indigo-400 transition-colors"
              />
            </div>
            <div>
              <label className="block text-[11px] font-semibold text-slate-500
                                uppercase tracking-wide mb-1.5">
                ⏰ Time
              </label>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-slate-200 text-sm
                           text-slate-700 bg-white focus:outline-none focus:ring-2
                           focus:ring-indigo-400 focus:border-indigo-400 transition-colors"
              />
            </div>
          </div>

          {/* Method */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500
                              uppercase tracking-wide mb-2">
              Method <span className="text-rose-500">*</span>
            </label>
            <div className="grid grid-cols-4 gap-2">
              {METHODS.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMethod(m)}
                  className={`flex flex-col items-center justify-center gap-1 px-2 py-2.5
                              rounded-xl border text-[11px] font-semibold transition-all
                              focus:outline-none focus:ring-2 focus:ring-indigo-400
                              ${method === m
                                ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm'
                                : 'bg-white border-slate-200 text-slate-600 hover:border-indigo-300 hover:bg-indigo-50'
                              }`}
                >
                  <span className="text-base leading-none">{METHOD_ICONS[m]}</span>
                  <span>{m}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Next Action */}
          <div>
            <label className="block text-[11px] font-semibold text-slate-500
                              uppercase tracking-wide mb-1.5">
              Next Action <span className="text-rose-500">*</span>
            </label>
            <div className="flex flex-wrap gap-1.5">
              {NEXT_ACTIONS.map((a) => (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAction(a)}
                  className={`px-2.5 py-1.5 rounded-lg border text-[11px] font-semibold
                              transition-all focus:outline-none focus:ring-2 focus:ring-indigo-400
                              ${action === a
                                ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm'
                                : 'bg-white border-slate-200 text-slate-600 hover:border-indigo-300 hover:bg-indigo-50'
                              }`}
                >
                  {a}
                </button>
              ))}
            </div>
          </div>

          {/* Error */}
          {error && (
            <p className="text-xs text-rose-600 bg-rose-50 border border-rose-200
                          rounded-lg px-3 py-2">
              {error}
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-5 py-4
                        border-t border-slate-100 bg-slate-50/60">
          {hasExisting ? (
            <button
              onClick={handleClear}
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs
                         font-semibold text-rose-600 border border-rose-200 bg-white
                         hover:bg-rose-50 disabled:opacity-60 transition-colors
                         focus:outline-none focus:ring-2 focus:ring-rose-400"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
              Clear
            </button>
          ) : (
            <button
              onClick={onClose}
              className="px-3 py-2 rounded-lg text-xs font-semibold text-slate-500
                         border border-slate-200 bg-white hover:bg-slate-50 transition-colors
                         focus:outline-none focus:ring-2 focus:ring-slate-300"
            >
              Cancel
            </button>
          )}

          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs
                       font-semibold bg-indigo-600 text-white hover:bg-indigo-700
                       disabled:opacity-60 transition-colors shadow-sm
                       focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {saving
              ? <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              : <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M5 13l4 4L19 7"/>
                </svg>
            }
            {saving ? 'Saving…' : 'Save Follow-up'}
          </button>
        </div>
      </div>
    </div>
  )
}
