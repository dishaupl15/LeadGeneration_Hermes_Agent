/**
 * PDLContactsPanel
 *
 * Modal/drawer showing People Data Labs contacts for one company.
 * Triggered by clicking "Find Contacts" on any lead row.
 *
 * Props:
 *   lead      – lead object (company_name, website, domain)
 *   onClose   – () => void
 *   hook      – return value of usePDLSearch()
 */

import { useEffect } from 'react'

/* ── Role badge colours ──────────────────────────────────────────────────── */
const ROLE_STYLES = {
  founder:            'bg-violet-100 text-violet-700 border-violet-200',
  co_founder:         'bg-violet-100 text-violet-700 border-violet-200',
  owner:              'bg-purple-100 text-purple-700 border-purple-200',
  ceo:                'bg-indigo-100 text-indigo-700 border-indigo-200',
  managing_director:  'bg-indigo-100 text-indigo-700 border-indigo-200',
  director:           'bg-sky-100   text-sky-700   border-sky-200',
  hr:                 'bg-emerald-100 text-emerald-700 border-emerald-200',
  talent_acquisition: 'bg-teal-100  text-teal-700  border-teal-200',
  recruitment:        'bg-cyan-100  text-cyan-700  border-cyan-200',
  other:              'bg-slate-100 text-slate-600 border-slate-200',
}

const ROLE_LABELS = {
  founder:            'Founder',
  co_founder:         'Co-Founder',
  owner:              'Owner',
  ceo:                'CEO',
  managing_director:  'MD',
  director:           'Director',
  hr:                 'HR',
  talent_acquisition: 'Talent Acq.',
  recruitment:        'Recruitment',
  other:              'Other',
}

/* ── Role classifier (for saved pipeline contacts that have title not email_type) */
function _roleFromTitle(title) {
  if (!title) return 'other'
  const t = ` ${title.toLowerCase().trim()} `
  if (t.includes('co-founder') || t.includes('cofounder')) return 'co_founder'
  if (t.includes('founder'))        return 'founder'
  if (t.includes('owner'))          return 'owner'
  if (t.includes('ceo') || t.includes('chief executive')) return 'ceo'
  if (t.includes('managing director') || t.includes(' md ')) return 'managing_director'
  if (t.includes('director'))       return 'director'
  if (t.includes('hr manager') || t.includes('human resources manager')) return 'hr'
  if (t.includes('human resources') || t.includes(' hr ')) return 'hr'
  if (t.includes('talent acquisition')) return 'talent_acquisition'
  if (t.includes('recruit'))        return 'recruitment'
  return 'other'
}

/* ── Source badge (for multi-provider contacts) ──────────────────────────── */
const SOURCE_BADGE_COLORS = {
  pdl:        'bg-blue-50 text-blue-700 border-blue-200',
  prospeo:    'bg-violet-50 text-violet-700 border-violet-200',
  contactout: 'bg-amber-50 text-amber-700 border-amber-200',
}
function SourceBadges({ sources }) {
  if (!sources || sources.length === 0) return null
  return (
    <div className="flex gap-1 flex-wrap">
      {sources.map(s => {
        const cls = SOURCE_BADGE_COLORS[s] || 'bg-slate-50 text-slate-600 border-slate-200'
        return (
          <span key={s} className={`inline-flex items-center px-1.5 py-0.5 rounded text-[9px]
                                    font-bold border uppercase tracking-wide ${cls}`}>
            {s}
          </span>
        )
      })}
    </div>
  )
}

function RoleBadge({ type }) {  const cls   = ROLE_STYLES[type] ?? ROLE_STYLES.other
  const label = ROLE_LABELS[type] ?? (type ?? 'Other')
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px]
                      font-semibold border ${cls} whitespace-nowrap`}>
      {label}
    </span>
  )
}

/* ── Confidence pill ─────────────────────────────────────────────────────── */
function ConfidencePill({ value }) {
  const pct = Math.round((value ?? 0) * 100)
  const cls = pct >= 85 ? 'bg-emerald-100 text-emerald-700'
            : pct >= 65 ? 'bg-amber-100 text-amber-700'
            :             'bg-rose-100 text-rose-600'
  return (
    <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${cls}`}>
      {pct}%
    </span>
  )
}

/* ── Single contact card ─────────────────────────────────────────────────── */
function ContactCard({ contact, idx }) {
  return (
    <div className={`rounded-xl border p-4 transition-shadow hover:shadow-sm
                     ${idx % 2 === 0 ? 'bg-white' : 'bg-slate-50/60'} border-slate-200`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        {/* Name + role */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-slate-800 leading-tight truncate">
            {contact.name ?? '—'}
          </p>
          {(contact.designation || contact.title) && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">
              {contact.designation || contact.title}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <RoleBadge type={contact.email_type} />
          <ConfidencePill value={contact.confidence} />
        </div>
      </div>

      {/* Contact details row */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-2">
        {contact.email ? (
          <a
            href={`mailto:${contact.email}`}
            className="inline-flex items-center gap-1.5 text-xs text-indigo-600
                       hover:text-indigo-800 hover:underline underline-offset-2 min-w-0"
            title={contact.email}
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
            </svg>
            <span className="truncate max-w-[200px]">{contact.email}</span>
          </a>
        ) : (
          <span className="text-xs text-slate-300 italic">No email</span>
        )}

        {/* Phone */}
        {contact.phone && (
          <a
            href={`tel:${contact.phone}`}
            className="inline-flex items-center gap-1.5 text-xs text-slate-600
                       hover:text-slate-800 whitespace-nowrap"
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257
                   1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0
                   01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
            </svg>
            {contact.phone}
          </a>
        )}

        {/* LinkedIn */}
        {contact.linkedin_url && (
          <a
            href={contact.linkedin_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-sky-600
                       hover:text-sky-800 hover:underline underline-offset-2"
            title="View LinkedIn profile"
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
              <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136
                       2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37
                       4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063
                       2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542
                       C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0
                       22.222 0h.003z"/>
            </svg>
            LinkedIn
          </a>
        )}
      </div>

      {/* Source badges row */}
      <div className="mt-2.5 flex items-center gap-2">
        {/* Multi-source badges (pipeline contacts) */}
        {contact.sources && contact.sources.length > 0 ? (
          <SourceBadges sources={contact.sources} />
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-violet-400 flex-shrink-0"/>
            <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wide">
              {contact.source ?? 'people_data_labs'}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Empty / error state ─────────────────────────────────────────────────── */
function NoContacts({ error }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center px-6">
      <div className="w-14 h-14 rounded-full bg-slate-100 flex items-center justify-center mb-4">
        <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
        </svg>
      </div>
      {error ? (
        <>
          <p className="text-sm font-semibold text-rose-600 mb-1">Search Failed</p>
          <p className="text-xs text-slate-500 max-w-xs leading-relaxed">{error}</p>
        </>
      ) : (
        <>
          <p className="text-sm font-semibold text-slate-700 mb-1">No contacts found</p>
          <p className="text-xs text-slate-400 max-w-xs leading-relaxed">
            PDL did not return decision-makers for this company. Try searching with the domain.
          </p>
        </>
      )}
    </div>
  )
}

/* ── Skeleton loading ────────────────────────────────────────────────────── */
function SkeletonCards() {
  return (
    <div className="flex flex-col gap-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-xl border border-slate-200 p-4 bg-white">
          <div className="flex justify-between mb-3">
            <div className="flex flex-col gap-1.5">
              <div className="shimmer h-3.5 w-36 rounded"/>
              <div className="shimmer h-2.5 w-24 rounded"/>
            </div>
            <div className="shimmer h-5 w-16 rounded-full"/>
          </div>
          <div className="shimmer h-3 w-48 rounded"/>
        </div>
      ))}
    </div>
  )
}

/* ── Main panel (modal overlay) ──────────────────────────────────────────── */
export default function PDLContactsPanel({ lead, onClose, hook }) {
  const { search, result, isLoading, error, clear } = hook

  // Pipeline-saved contacts (from PDL→Prospeo→ContactOut orchestrator)
  const savedContacts = Array.isArray(lead?.contacts)
    ? lead.contacts.filter(c => (c.name || '').trim())
    : []
  const hasSavedContacts = savedContacts.length > 0

  // Run live PDL search only when no saved contacts exist
  useEffect(() => {
    if (!lead) return
    if (hasSavedContacts) return   // already have enriched contacts — skip live search
    const domain = lead.domain
      || (lead.website
            ? lead.website.replace(/^https?:\/\/(www\.)?/, '').split('/')[0]
            : null)
    search({
      company_name: lead.company_name,
      domain,
      website: lead.website,
    })
    return () => clear()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lead?.company_name])

  // Close on Escape key
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  if (!lead) return null

  // Use saved contacts if available, otherwise fall back to live PDL result
  const contacts    = hasSavedContacts ? savedContacts : (result?.contacts ?? [])
  const source      = hasSavedContacts ? 'pipeline' : 'pdl_live'
  const emailsFound = hasSavedContacts
    ? savedContacts.filter(c => c.email).length
    : (result?.emails_found ?? 0)
  const phonesFound = hasSavedContacts
    ? savedContacts.filter(c => c.phone).length
    : 0
  const apiCalls    = hasSavedContacts ? 0 : (result?.pdl_api_calls ?? 0)
  const elapsed     = hasSavedContacts ? null : (result?.elapsed_seconds ?? null)

  // Normalise saved contacts to match ContactCard expected shape
  const normalisedContacts = hasSavedContacts
    ? savedContacts.map(c => ({
        name:         c.name,
        designation:  c.title,
        email:        c.email,
        phone:        c.phone,
        linkedin_url: c.linkedin_url,
        email_type:   _roleFromTitle(c.title),
        confidence:   c.confidence ?? 0,
        source:       (c.sources || []).join('+') || 'pipeline',
        sources:      c.sources || [],
      }))
    : contacts

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={`PDL contacts for ${lead.company_name}`}
    >
      {/* Dimmed bg — click to close */}
      <div
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Drawer panel */}
      <div className="relative z-10 h-full w-full max-w-md bg-white shadow-2xl
                      flex flex-col overflow-hidden fade-in-up"
           style={{ animation: 'slideInRight 0.25s ease-out both' }}>

        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4
                        border-b border-slate-200 bg-white flex-shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              {/* Mode badge: pipeline-saved vs live PDL */}
              {hasSavedContacts ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px]
                                 font-bold bg-emerald-600 text-white uppercase tracking-wide">
                  Enriched
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px]
                                 font-bold bg-violet-600 text-white uppercase tracking-wide">
                  PDL Live
                </span>
              )}
              <span className="text-xs text-slate-500 font-medium">
                {hasSavedContacts ? 'Pipeline Contacts' : 'People Data Labs'}
              </span>
            </div>
            <h2 className="text-sm font-bold text-slate-900 leading-snug truncate max-w-[300px]">
              {lead.company_name}
            </h2>
            {(lead.domain || result?.company_domain) && (
              <p className="text-xs text-slate-400 mt-0.5">{lead.domain || result?.company_domain}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-full
                       text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
            aria-label="Close panel"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        {/* Stats bar */}
        {(hasSavedContacts || (result && !isLoading)) && (
          <div className="flex items-center gap-4 px-5 py-2.5 bg-slate-50
                          border-b border-slate-200 text-xs text-slate-600 flex-shrink-0 flex-wrap">
            <span>
              👤 <strong className="text-slate-800">{normalisedContacts.length}</strong> contacts
            </span>
            {emailsFound > 0 && (
              <span>✉️ <strong className="text-slate-800">{emailsFound}</strong> emails</span>
            )}
            {phonesFound > 0 && (
              <span>📞 <strong className="text-slate-800">{phonesFound}</strong> phones</span>
            )}
            {!hasSavedContacts && apiCalls > 0 && (
              <span>🔗 <strong className="text-slate-800">{apiCalls}</strong> API calls</span>
            )}
            {elapsed != null && (
              <span className="ml-auto text-slate-400">{elapsed}s</span>
            )}
            {hasSavedContacts && (
              <span className="ml-auto text-emerald-600 font-semibold text-[10px]">
                ✓ from pipeline
              </span>
            )}
          </div>
        )}

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 scrollbar-thin">
          {!hasSavedContacts && isLoading ? (
            <SkeletonCards />
          ) : !hasSavedContacts && error ? (
            <NoContacts error={error} />
          ) : normalisedContacts.length === 0 ? (
            <NoContacts />
          ) : (
            <div className="flex flex-col gap-3">
              {normalisedContacts.map((c, i) => (
                <ContactCard key={`${c.name}-${i}`} contact={c} idx={i} />
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-5 py-3 border-t border-slate-200 bg-slate-50/80
                        flex items-center justify-between">
          <span className="text-[10px] text-slate-400 uppercase tracking-wide font-medium">
            {hasSavedContacts
              ? 'PDL · Prospeo · ContactOut waterfall'
              : 'Source: People Data Labs · live search'}
          </span>
          <button
            onClick={onClose}
            className="text-xs text-slate-500 hover:text-slate-800 font-medium
                       px-3 py-1.5 rounded-lg hover:bg-slate-200 transition-colors"
          >
            Close
          </button>
        </div>
      </div>

      {/* Slide-in animation */}
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  )
}
