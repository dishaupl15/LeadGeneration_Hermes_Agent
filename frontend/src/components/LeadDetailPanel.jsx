import { useState, useCallback } from 'react'
import { addLeadNote, updateLeadFollowUp, enrichLeadWithOrigami } from '../services/api'

/** Format ISO timestamp → "06 Jan 2025, 14:32" */
function fmtDateTime(iso) {
  if (!iso) return ''
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

/** Small badge for source/provider labels */
function SourceBadge({ source, status }) {
  if (!source) return null
  const srcLower = (source || '').toLowerCase()
  const color =
    srcLower === 'origami'     ? 'bg-violet-100 text-violet-700 border-violet-200' :
    srcLower === 'pdl'         ? 'bg-sky-100 text-sky-700 border-sky-200' :
    srcLower === 'prospeo'     ? 'bg-indigo-100 text-indigo-700 border-indigo-200' :
    srcLower === 'hunter'      ? 'bg-amber-100 text-amber-700 border-amber-200' :
    srcLower === 'contactout'  ? 'bg-teal-100 text-teal-700 border-teal-200' :
    srcLower === 'companyenrich'? 'bg-emerald-100 text-emerald-700 border-emerald-200' :
    srcLower === 'google_maps' ? 'bg-rose-100 text-rose-700 border-rose-200' :
                                  'bg-slate-100 text-slate-600 border-slate-200'

  const isVerified = status && (status.includes('verified') || status.includes('valid'))
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] font-semibold uppercase tracking-wide ${color}`}>
      {source}
      {isVerified && <span className="text-emerald-500" title="Verified">✓</span>}
    </span>
  )
}

/** Tier-coloured badge for Origami contact tier */
function TierBadge({ tier, label }) {
  const color =
    tier === 1 ? 'bg-violet-100 text-violet-700' :
    tier === 2 ? 'bg-sky-100 text-sky-700' :
    tier === 3 ? 'bg-indigo-100 text-indigo-700' :
    tier === 4 ? 'bg-amber-100 text-amber-700' :
                  'bg-slate-100 text-slate-500'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-bold uppercase ${color}`}>
      {label || 'Other'}
    </span>
  )
}

/** Origami status badge */
function OrigamiStatusBadge({ founderStatus, origamiEnriched }) {
  if (origamiEnriched === true && (founderStatus === 'found' || founderStatus === 'found_decision_maker')) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-700 border border-emerald-200">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"/>
        {founderStatus === 'found' ? 'Enriched — Founder Found' : 'Enriched — Decision Maker'}
      </span>
    )
  }
  if (founderStatus === 'not_found') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-700 border border-amber-200">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500"/>
        Not Found
      </span>
    )
  }
  if (founderStatus === 'error') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-200">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500"/>
        Error
      </span>
    )
  }
  if (founderStatus === 'skipped' || !origamiEnriched) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-500 border border-slate-200">
        <span className="w-1.5 h-1.5 rounded-full bg-slate-400"/>
        Not Run
      </span>
    )
  }
  // Partial — enriched but no founder
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-700 border border-blue-200">
      <span className="w-1.5 h-1.5 rounded-full bg-blue-500"/>
      Partial
    </span>
  )
}

export default function LeadDetailPanel({ lead: initialLead, onClose, onLeadUpdate }) {
  const [lead, setLead] = useState(initialLead)

  const [noteText,    setNoteText]    = useState('')
  const [savingNote,  setSavingNote]  = useState(false)
  const [noteError,   setNoteError]   = useState('')

  const [followUpDate,    setFollowUpDate]    = useState(lead.follow_up_date ?? '')
  const [savingFollowUp,  setSavingFollowUp]  = useState(false)
  const [followUpError,   setFollowUpError]   = useState('')
  const [followUpSaved,   setFollowUpSaved]   = useState(false)

  // Origami enrichment state
  const [origamiRunning,  setOrigamiRunning]  = useState(false)
  const [origamiError,    setOrigamiError]    = useState('')
  const [origamiResult,   setOrigamiResult]   = useState(null)

  // Local copy of notes so UI updates immediately
  const [notes, setNotes] = useState(lead.notes ?? [])

  /** Apply an updated lead document from any API response */
  const applyLeadUpdate = useCallback((updatedDoc) => {
    if (!updatedDoc) return
    setLead(prev => ({ ...prev, ...updatedDoc }))
    if (onLeadUpdate) onLeadUpdate(updatedDoc)
  }, [onLeadUpdate])

  const handleAddNote = async () => {
    const text = noteText.trim()
    if (!text) return
    setSavingNote(true)
    setNoteError('')
    try {
      const res = await addLeadNote(
        lead.id ?? lead._id,
        text,
        lead.category ?? null,
      )
      const newNote = res.note
      setNotes(prev => [...prev, newNote])
      setNoteText('')
      applyLeadUpdate(res.lead)
    } catch (err) {
      setNoteError(err.message || 'Failed to save note.')
    } finally {
      setSavingNote(false)
    }
  }

  const handleSaveFollowUp = async (dateOverride) => {
    const dateToSave = dateOverride !== undefined ? dateOverride : followUpDate
    setSavingFollowUp(true)
    setFollowUpError('')
    setFollowUpSaved(false)
    try {
      const res = await updateLeadFollowUp(
        lead.id ?? lead._id,
        dateToSave || null,
        lead.category ?? null,
      )
      setFollowUpSaved(true)
      setTimeout(() => setFollowUpSaved(false), 2000)
      applyLeadUpdate(res.lead)
    } catch (err) {
      setFollowUpError(err.message || 'Failed to save follow-up date.')
    } finally {
      setSavingFollowUp(false)
    }
  }

  const handleRunOrigami = async () => {
    if (origamiRunning) return
    setOrigamiRunning(true)
    setOrigamiError('')
    setOrigamiResult(null)
    try {
      const res = await enrichLeadWithOrigami(
        lead.id ?? lead._id,
        lead.category ?? null,
      )
      setOrigamiResult(res.origami ?? {})
      if (res.lead) {
        applyLeadUpdate(res.lead)
        // Sync notes from updated lead if changed
        if (res.lead.notes) setNotes(res.lead.notes)
      }
    } catch (err) {
      setOrigamiError(err.message || 'Origami enrichment failed.')
    } finally {
      setOrigamiRunning(false)
    }
  }

  const isInterested = (lead.status ?? 'new') === 'interested'

  // Derive Origami data from current lead state
  const origamiEnriched   = lead.origami_enriched ?? false
  const founderStatus     = lead.founder_status ?? 'skipped'
  const origamiConfidence = lead.origami_confidence ?? 0
  const origamiSource     = lead.origami_source || 'origami'
  const people            = lead.people ?? []
  const contacts          = lead.contacts ?? []

  // Field verification map for source labels
  const fv = lead._field_verification ?? lead.field_verification ?? {}

  /** Get source info for a field */
  const fieldSource = (field) => {
    const v = fv[field]
    if (!v || typeof v !== 'object') return null
    return { source: v.source || '', status: v.status || '' }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center
                 bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[90vh]
                      flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-6 py-4
                        border-b border-slate-100">
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-bold text-slate-800 truncate">
              {lead.company_name || '—'}
            </h2>
            <p className="text-xs text-slate-400 mt-0.5 truncate">
              {lead.website || lead.domain || ''}
            </p>
            <div className="flex flex-wrap items-center gap-2 mt-2">
              {/* Status badge */}
              {(() => {
                const s = lead.status ?? 'new'
                const cfg = s === 'interested'
                  ? 'bg-emerald-100 text-emerald-700'
                  : s === 'not_interested'
                    ? 'bg-rose-100 text-rose-700'
                    : 'bg-sky-100 text-sky-700'
                const label = s === 'not_interested' ? 'Not Interested' : s === 'interested' ? 'Interested' : 'New'
                return (
                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${cfg}`}>
                    <span className="w-1 h-1 rounded-full bg-current flex-shrink-0"/>
                    {label}
                  </span>
                )
              })()}
              {lead.category && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 font-medium">
                  {lead.category}
                </span>
              )}
              {(lead.platform || lead.research_source) && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-violet-50 text-violet-600 font-medium">
                  {lead.platform || lead.research_source}
                </span>
              )}
              {lead.created_at && (
                <span className="text-[10px] text-slate-400">
                  Created: {String(lead.created_at).slice(0,10)}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center
                       text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">

          {/* ── Contact Information ── */}
          {(lead.email || lead.company_number || lead.founder_name || lead.address) && (
            <section>
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                </svg>
                Contact Information
              </h3>
              <dl className="space-y-1.5 text-xs">
                {lead.founder_name && (
                  <div className="flex gap-2">
                    <dt className="text-slate-400 w-20 flex-shrink-0">Founder</dt>
                    <dd className="text-slate-700 font-medium flex items-center gap-1.5">
                      {lead.founder_name}
                      {fieldSource('founder') && (
                        <SourceBadge source={fieldSource('founder').source} status={fieldSource('founder').status}/>
                      )}
                    </dd>
                  </div>
                )}
                {(lead.email || (lead.emails && lead.emails[0])) && (
                  <div className="flex gap-2">
                    <dt className="text-slate-400 w-20 flex-shrink-0">Email</dt>
                    <dd className="text-indigo-600 truncate flex items-center gap-1.5">
                      <a href={`mailto:${lead.email || lead.emails[0]}`}>
                        {lead.email || lead.emails[0]}
                      </a>
                      {fieldSource('email') && (
                        <SourceBadge source={fieldSource('email').source} status={fieldSource('email').status}/>
                      )}
                    </dd>
                  </div>
                )}
                {(lead.company_number || (lead.phones && lead.phones[0])) && (
                  <div className="flex gap-2">
                    <dt className="text-slate-400 w-20 flex-shrink-0">Phone</dt>
                    <dd className="text-slate-700 flex items-center gap-1.5">
                      {lead.company_number || lead.phones[0]}
                      {fieldSource('phone') && (
                        <SourceBadge source={fieldSource('phone').source} status={fieldSource('phone').status}/>
                      )}
                    </dd>
                  </div>
                )}
                {lead.address && (
                  <div className="flex gap-2">
                    <dt className="text-slate-400 w-20 flex-shrink-0">Address</dt>
                    <dd className="text-slate-600 leading-snug">{lead.address}</dd>
                  </div>
                )}
              </dl>
            </section>
          )}

          {/* ══════════════════════════════════════════════════════════════
              ORIGAMI ENRICHMENT SECTION
              ══════════════════════════════════════════════════════════════ */}
          <section className="border border-violet-100 rounded-xl p-4 bg-violet-50/30">
            {/* Section header + Run button */}
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-bold text-violet-700 uppercase tracking-widest flex items-center gap-2">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                </svg>
                Origami Enrichment
              </h3>
              <button
                onClick={handleRunOrigami}
                disabled={origamiRunning}
                title="Run Origami to find founder, CEO and decision-maker contacts"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold
                           bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60
                           transition-colors focus:outline-none focus:ring-2 focus:ring-violet-400"
              >
                {origamiRunning
                  ? <><svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                      </svg> Running…</>
                  : <><svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z"/>
                      </svg> Run Origami</>
                }
              </button>
            </div>

            {origamiError && (
              <p className="mb-3 text-[11px] text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                {origamiError}
              </p>
            )}

            {origamiResult && origamiResult.error && (
              <p className="mb-3 text-[11px] text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                Origami API error: {origamiResult.error}
              </p>
            )}

            {/* Status row */}
            <div className="flex items-center gap-2 mb-3">
              <span className="text-[10px] text-slate-500 font-semibold">Status:</span>
              <OrigamiStatusBadge founderStatus={founderStatus} origamiEnriched={origamiEnriched}/>
              {origamiEnriched && origamiConfidence > 0 && (
                <span className="text-[10px] text-slate-400">
                  conf: <strong className="text-violet-600">{Math.round(origamiConfidence * 100)}%</strong>
                </span>
              )}
              {origamiEnriched && (
                <SourceBadge source={origamiSource}/>
              )}
            </div>

            {/* Company + Website quick view */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 mb-3 text-[11px]">
              <div>
                <span className="text-slate-400">Company: </span>
                <span className="text-slate-700 font-medium">{lead.company_name || '—'}</span>
              </div>
              <div>
                <span className="text-slate-400">Website: </span>
                {lead.website
                  ? <a href={lead.website} target="_blank" rel="noopener noreferrer"
                       className="text-indigo-600 hover:underline truncate">
                      {lead.website.replace(/^https?:\/\/(www\.)?/, '').split('/')[0]}
                    </a>
                  : <span className="text-slate-300">—</span>
                }
              </div>
            </div>

            {/* Founder row */}
            <div className="bg-white rounded-lg border border-violet-100 p-3 mb-3">
              <p className="text-[10px] font-bold text-violet-600 uppercase tracking-widest mb-2">
                Founder / Owner
              </p>
              <dl className="space-y-1 text-[11px]">
                <div className="flex gap-2">
                  <dt className="text-slate-400 w-20 flex-shrink-0">Name</dt>
                  <dd className="text-slate-700 font-medium">
                    {lead.founder_name || <span className="text-slate-300 italic">not found</span>}
                    {lead.founder_title && (
                      <span className="ml-1.5 text-slate-400 font-normal">({lead.founder_title})</span>
                    )}
                  </dd>
                </div>
                <div className="flex gap-2 items-center">
                  <dt className="text-slate-400 w-20 flex-shrink-0">Email</dt>
                  <dd className="flex items-center gap-1.5 flex-wrap">
                    {lead.founder_email
                      ? <a href={`mailto:${lead.founder_email}`}
                           className="text-indigo-600 hover:underline">{lead.founder_email}</a>
                      : <span className="text-slate-300 italic">not found</span>
                    }
                    {fieldSource('email') && lead.founder_email && (
                      <SourceBadge source={fieldSource('email').source} status={fieldSource('email').status}/>
                    )}
                    {origamiEnriched && lead.founder_email && !fieldSource('email') && (
                      <SourceBadge source="origami"/>
                    )}
                  </dd>
                </div>
                <div className="flex gap-2 items-center">
                  <dt className="text-slate-400 w-20 flex-shrink-0">Phone</dt>
                  <dd className="flex items-center gap-1.5 flex-wrap">
                    {lead.founder_number
                      ? <span className="text-slate-700">{lead.founder_number}</span>
                      : (lead.company_number
                          ? <><span className="text-slate-700">{lead.company_number}</span>
                              <span className="text-[9px] text-slate-400">(company)</span></>
                          : <span className="text-slate-300 italic">not found</span>)
                    }
                    {fieldSource('phone') && (lead.founder_number || lead.company_number) && (
                      <SourceBadge source={fieldSource('phone').source} status={fieldSource('phone').status}/>
                    )}
                  </dd>
                </div>
                {lead.founder_profile_url && (
                  <div className="flex gap-2 items-center">
                    <dt className="text-slate-400 w-20 flex-shrink-0">Profile</dt>
                    <dd>
                      <a href={lead.founder_profile_url} target="_blank" rel="noopener noreferrer"
                         className="text-indigo-600 hover:underline text-[11px] truncate max-w-[200px] inline-block">
                        {lead.founder_profile_url.replace(/^https?:\/\/(www\.)?/, '').split('/').slice(0,3).join('/')}
                      </a>
                    </dd>
                  </div>
                )}
              </dl>
            </div>

            {/* Other decision makers (people[]) */}
            {people.length > 0 && (
              <div className="mb-3">
                <p className="text-[10px] font-bold text-violet-600 uppercase tracking-widest mb-2">
                  Other Decision Makers ({people.length})
                </p>
                <div className="space-y-2">
                  {people.map((p, i) => (
                    <div key={i}
                         className="bg-white rounded-lg border border-violet-100 px-3 py-2 text-[11px]">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-semibold text-slate-700">{p.name || '—'}</span>
                        <TierBadge tier={p.tier} label={p.tier_label}/>
                        <SourceBadge source={p.source || 'origami'}/>
                        {p.confidence > 0 && (
                          <span className="text-[9px] text-slate-400 ml-auto">
                            {Math.round(p.confidence * 100)}%
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-slate-500">
                        {p.title && <span>📌 {p.title}</span>}
                        {p.email
                          ? <a href={`mailto:${p.email}`} className="text-indigo-600 hover:underline">✉ {p.email}</a>
                          : <span className="text-slate-300 italic">no email</span>
                        }
                        {p.phone
                          ? <span>📞 {p.phone}</span>
                          : <span className="text-slate-300 italic">no phone</span>
                        }
                        {p.linkedin_url && (
                          <a href={p.linkedin_url} target="_blank" rel="noopener noreferrer"
                             className="text-indigo-600 hover:underline">🔗 LinkedIn</a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Enriched contacts from waterfall (PDL/Prospeo/ContactOut/Hunter + Origami merged) */}
            {contacts.length > 0 && (
              <div>
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">
                  All Enriched Contacts ({contacts.length} · deduped)
                </p>
                <div className="space-y-1.5">
                  {contacts.map((ct, i) => (
                    <div key={i}
                         className="bg-slate-50 rounded-lg border border-slate-100 px-3 py-2 text-[11px]">
                      <div className="flex items-center gap-2 flex-wrap mb-0.5">
                        <span className="font-semibold text-slate-700">{ct.name || '—'}</span>
                        {(ct.sources || []).map(s => (
                          <SourceBadge key={s} source={s}/>
                        ))}
                        {ct.confidence > 0 && (
                          <span className="text-[9px] text-slate-400 ml-auto">
                            {Math.round(ct.confidence * 100)}%
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-slate-500">
                        {ct.title && <span className="text-slate-400">📌 {ct.title}</span>}
                        {ct.email
                          ? <a href={`mailto:${ct.email}`} className="text-indigo-600 hover:underline">✉ {ct.email}</a>
                          : <span className="text-slate-300 italic text-[10px]">no email</span>
                        }
                        {ct.phone && <span>📞 {ct.phone}</span>}
                        {ct.linkedin_url && (
                          <a href={ct.linkedin_url} target="_blank" rel="noopener noreferrer"
                             className="text-indigo-600 hover:underline">🔗</a>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state when Origami hasn't run */}
            {!origamiEnriched && people.length === 0 && contacts.length === 0 && (
              <p className="text-[11px] text-slate-400 italic text-center py-2">
                Click "Run Origami" to find the founder, CEO and other decision-makers.
              </p>
            )}
          </section>

          {/* ── Follow-up Date ── */}
          <section>
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
              </svg>
              Follow-up Date
              {!isInterested && (
                <span className="text-[10px] font-normal text-slate-400 normal-case tracking-normal">
                  (mark as Interested to schedule)
                </span>
              )}
            </h3>

            <div className="flex items-center gap-2">
              <input
                type="date"
                value={followUpDate}
                onChange={(e) => { setFollowUpDate(e.target.value); setFollowUpSaved(false) }}
                min={new Date().toISOString().split('T')[0]}
                className="crm-input flex-1 text-sm"
              />
              <button
                onClick={handleSaveFollowUp}
                disabled={savingFollowUp}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold
                           bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-60
                           transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-400"
              >
                {savingFollowUp
                  ? <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                    </svg>
                  : followUpSaved ? '✓ Saved' : 'Save'
                }
              </button>
              {followUpDate && (
                <button
                  onClick={() => { setFollowUpDate(''); handleSaveFollowUp('') }}
                  title="Clear follow-up date"
                  className="text-xs text-slate-400 hover:text-rose-500 transition-colors px-1"
                >✕</button>
              )}
            </div>
            {followUpError && (
              <p className="mt-1.5 text-xs text-rose-600">{followUpError}</p>
            )}
            {lead.follow_up_date && (
              <p className="mt-1.5 text-xs text-slate-400">
                Current: <span className="font-semibold text-indigo-600">{lead.follow_up_date}</span>
              </p>
            )}
          </section>

          {/* ── Notes ── */}
          <section>
            <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3 flex items-center gap-2">
              <svg className="w-3.5 h-3.5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
              </svg>
              Notes
              {notes.length > 0 && (
                <span className="inline-flex items-center justify-center w-5 h-5 rounded-full
                                 bg-amber-100 text-amber-700 text-[10px] font-bold">
                  {notes.length}
                </span>
              )}
            </h3>

            <div className="flex flex-col gap-2 mb-4">
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleAddNote()
                }}
                placeholder="Add a note… (Ctrl+Enter to save)"
                rows={3}
                maxLength={2000}
                className="crm-input resize-none text-sm leading-relaxed"
              />
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-300">{noteText.length}/2000</span>
                <button
                  onClick={handleAddNote}
                  disabled={savingNote || !noteText.trim()}
                  className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold
                             bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50
                             transition-colors focus:outline-none focus:ring-2 focus:ring-amber-400"
                >
                  {savingNote
                    ? <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                      </svg>
                    : <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4"/>
                      </svg>
                  }
                  Add Note
                </button>
              </div>
              {noteError && <p className="text-xs text-rose-600">{noteError}</p>}
            </div>

            {notes.length === 0 ? (
              <p className="text-xs text-slate-300 italic text-center py-4">No notes yet.</p>
            ) : (
              <ul className="space-y-2.5">
                {[...notes].reverse().map((note, i) => (
                  <li key={i}
                      className="bg-amber-50 border border-amber-100 rounded-xl px-4 py-3">
                    <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap">
                      {note.text}
                    </p>
                    <p className="text-[10px] text-slate-400 mt-1.5">
                      {fmtDateTime(note.created_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}
