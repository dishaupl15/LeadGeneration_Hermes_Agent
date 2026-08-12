import { useState } from 'react'
import EmptyState from './EmptyState'
import PDLContactsPanel from './PDLContactsPanel'
import { usePDLSearch } from '../hooks/usePDLSearch'

/* ════════════════════════════════════════════════════════════════════
   HELPERS
   ════════════════════════════════════════════════════════════════════ */

/** First non-empty string from an array, or null */
function pickFirst(arr) {
  if (!arr) return null
  if (!Array.isArray(arr)) return String(arr).trim() || null
  for (const v of arr) {
    const s = String(v ?? '').trim()
    if (s) return s
  }
  return null
}

/** Build a full address string from all available address fields */
function resolveAddress(lead) {
  // 1. Prefer the dedicated address field (already cleaned by backend)
  const raw = (lead.address || '').trim()
  if (raw) {
    // If it's too long (paragraph) try just the first sentence
    if (raw.split(' ').length > 25) {
      const first = raw.split('.')[0].trim()
      if (first.length > 10) return first
    }
    return raw
  }
  // 2. Assemble from structured fields
  const parts = [
    lead.city,
    lead.state,
    lead.postal_code,
    lead.country,
  ].filter(Boolean).map(s => String(s).trim()).filter(Boolean)
  return parts.length ? parts.join(', ') : null
}

/** Resolve best single email */
function resolveEmail(lead) {
  return lead.email || pickFirst(lead.emails)
}

/** Resolve best company phone */
function resolvePhone(lead) {
  // Prefer enriched company_number, then first from phones[]
  const cn = (lead.company_number || '').trim()
  if (cn) return cn
  return pickFirst(lead.phones)
}

/** Format ISO timestamp → human date */
function fmtDate(iso) {
  if (!iso) return null
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    }).format(new Date(iso))
  } catch {
    // If direct parse fails, try stripping the fractional seconds
    try { return new Intl.DateTimeFormat('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    }).format(new Date(iso.replace(/\.\d+/, ''))) } catch { return iso }
  }
}

/**
 * Normalise a phone number to E.164 digits for WhatsApp.
 * Strips spaces, dashes, parentheses, dots.
 * Adds +91 prefix for 10-digit Indian mobiles that don't already have a country code.
 */
function waNumber(raw) {
  if (!raw) return null
  // Remove all non-digit characters except leading +
  const stripped = raw.replace(/[^\d+]/g, '')
  // Already has country code (starts with + or 00)
  if (stripped.startsWith('+')) return stripped.replace('+', '')
  if (stripped.startsWith('00')) return stripped.slice(2)
  // 10-digit Indian mobile → add 91
  if (/^[6-9]\d{9}$/.test(stripped)) return '91' + stripped
  // 11-digit with leading 0 → drop 0, add 91
  if (/^0[6-9]\d{9}$/.test(stripped)) return '91' + stripped.slice(1)
  // Return as-is (will still open WhatsApp, may fail for invalid numbers)
  return stripped
}

/** WhatsApp redirect button */
function WAButton({ phone }) {
  const num = waNumber(phone)
  if (!num) return null
  const href = `https://wa.me/${num}`
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title={`WhatsApp ${phone}`}
      className="
        inline-flex items-center justify-center w-7 h-7 rounded-full flex-shrink-0
        bg-[#25D366] hover:bg-[#1ebe5d] active:bg-[#17a84f]
        text-white shadow-sm transition-colors duration-150
        focus:outline-none focus:ring-2 focus:ring-[#25D366] focus:ring-offset-1
      "
      aria-label={`Open WhatsApp chat with ${phone}`}
    >
      {/* WhatsApp icon (official path) */}
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
      </svg>
    </a>
  )
}

/** Shorten a URL to domain + first path segment */
function shortUrl(url) {
  if (!url) return null
  try {
    const u = new URL(url)
    const path = u.pathname === '/' ? '' : '/' + u.pathname.split('/').filter(Boolean)[0]
    return u.hostname.replace(/^www\./, '') + path
  } catch {
    return url.replace(/^https?:\/\/(www\.)?/, '').split('/').slice(0, 2).join('/')
  }
}

/* ════════════════════════════════════════════════════════════════════
   SMALL UI ATOMS
   ════════════════════════════════════════════════════════════════════ */

/** Rendered when a field genuinely has no data at all */
function Nil() {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate-300 font-normal italic">
      N/A
    </span>
  )
}

/** Avatar with colored initials */
const COLORS = [
  'bg-violet-100 text-violet-700', 'bg-sky-100 text-sky-700',
  'bg-emerald-100 text-emerald-700', 'bg-amber-100 text-amber-700',
  'bg-rose-100 text-rose-700', 'bg-indigo-100 text-indigo-700',
  'bg-teal-100 text-teal-700', 'bg-pink-100 text-pink-700',
]
function Avatar({ name, index }) {
  const color    = COLORS[index % COLORS.length]
  const initials = (name || '?').split(' ').slice(0, 2)
    .map(w => w[0]?.toUpperCase() ?? '').join('') || '?'
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center
                     text-xs font-bold flex-shrink-0 ${color}`}>
      {initials}
    </div>
  )
}

/** Confidence: percentage text + color-coded bar */
function ConfidenceBar({ value }) {
  if (value == null || value === '') return <Nil />
  const pct = Math.round(Number(value) * 100)
  const bar = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-400' : 'bg-rose-400'
  const txt = pct >= 80 ? 'text-emerald-700' : pct >= 50 ? 'text-amber-700' : 'text-rose-600'
  return (
    <div className="flex flex-col gap-1 min-w-[76px]">
      <span className={`text-xs font-bold ${txt}`}>{pct}%</span>
      <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** Status dropdown — CRM update status per company */
const STATUS_OPTIONS = [
  { value: '',              label: 'Set status…',      bg: 'bg-slate-100',    text: 'text-slate-400',   dot: 'bg-slate-300'   },
  { value: 'new',           label: 'New Data',         bg: 'bg-sky-50',       text: 'text-sky-700',     dot: 'bg-sky-400'     },
  { value: 'contacted',     label: 'Contacted',        bg: 'bg-violet-50',    text: 'text-violet-700',  dot: 'bg-violet-400'  },
  { value: 'follow_up',     label: 'Follow-up',        bg: 'bg-amber-50',     text: 'text-amber-700',   dot: 'bg-amber-400'   },
  { value: 'interested',    label: 'Interested',       bg: 'bg-emerald-50',   text: 'text-emerald-700', dot: 'bg-emerald-400' },
  { value: 'not_interested',label: 'Not Interested',   bg: 'bg-rose-50',      text: 'text-rose-700',    dot: 'bg-rose-400'    },
  { value: 'closed',        label: 'Closed',           bg: 'bg-slate-100',    text: 'text-slate-600',   dot: 'bg-slate-400'   },
]

function StatusDropdown({ leadId, value, onChange }) {
  const selected = STATUS_OPTIONS.find(o => o.value === (value || '')) || STATUS_OPTIONS[0]

  return (
    <div className="relative min-w-[148px]">
      {/* Colored chip display */}
      <div className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border
                       ${value ? `${selected.bg} border-current/20` : 'bg-white border-slate-200'}
                       text-xs font-semibold ${selected.text} pointer-events-none
                       absolute inset-0 z-0`}>
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${selected.dot}`} />
        <span className="truncate">{selected.label}</span>
        <svg className="w-3 h-3 ml-auto flex-shrink-0 opacity-60" fill="none"
          stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7"/>
        </svg>
      </div>

      {/* Invisible native select on top for interaction */}
      <select
        value={value || ''}
        onChange={(e) => onChange(leadId, e.target.value)}
        className="relative z-10 w-full h-full opacity-0 cursor-pointer
                   text-xs py-1.5 px-2.5 rounded-lg"
        title="Set company status"
      >
        {STATUS_OPTIONS.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}
function SortIcon({ dir }) {
  if (!dir) return (
    <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="none"
      stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
    </svg>
  )
  return dir === 'asc' ? (
    <svg className="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" fill="none"
      stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 15l7-7 7 7" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5 text-indigo-600 flex-shrink-0" fill="none"
      stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
    </svg>
  )
}

/* ════════════════════════════════════════════════════════════════════
   SKELETON ROW (loading state)
   ════════════════════════════════════════════════════════════════════ */
function SkeletonRow({ index }) {
  // 11 columns: #, Company, Email, Founder, Phone, Address, Source, Verified, Status, Website, Contacts
  const ws = ['w-5','w-44','w-44','w-28','w-28','w-44','w-32','w-24','w-36','w-32','w-24']
  return (
    <tr className={index % 2 === 0 ? 'bg-white' : 'bg-slate-50/60'}>
      {ws.map((w, i) => (
        <td key={i} className="px-4 py-4">
          <div className={`shimmer h-3.5 ${w} rounded`} />
        </td>
      ))}
    </tr>
  )
}

/* ════════════════════════════════════════════════════════════════════
   DATA ROW — columns in the exact requested order
   ════════════════════════════════════════════════════════════════════

   Column order (matches the JSON field order you specified):
     1.  #
     2.  company_name
     3.  email
     4.  founder_number  (+ founder_name as sub-label)
     5.  company_number  (phone)
     6.  address
     7.  source_url
     8.  last_verified
     9.  confidence
    10.  website         (clickable link, shown last)
    11.  contacts        (PDL "Find Contacts" button)
   ════════════════════════════════════════════════════════════════════ */
function LeadRow({ lead, index, onFindContacts, status, onStatusChange }) {
  // ── Resolve all fields with fallbacks ──────────────────────────
  const email         = resolveEmail(lead)
  const phone         = resolvePhone(lead)
  const address       = resolveAddress(lead)
  const founderName   = (lead.founder_name  || '').trim() || null
  const founderPhone  = (lead.founder_number || '').trim() || null
  const srcUrl        = (lead.source_url || '').trim() || null
  const verified      = fmtDate(lead.last_verified)
  const confidence    = lead.confidence ?? null
  const website       = (lead.website || '').trim() || null
  const companyName   = (lead.company_name || '').trim() || '—'

  return (
    <tr className={`border-b border-slate-100 transition-colors duration-100 cursor-default
                    ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'} hover:bg-indigo-50/40`}>

      {/* 1. # */}
      <td className="px-4 py-3.5 text-xs text-slate-400 font-medium w-10">
        {index + 1}
      </td>

      {/* 2. company_name */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <Avatar name={companyName} index={index} />
          <span className="text-sm font-semibold text-slate-800 leading-tight
                           line-clamp-2 max-w-[160px]">
            {companyName}
          </span>
        </div>
      </td>

      {/* 3. email */}
      <td className="px-4 py-3.5 max-w-[200px]">
        {email
          ? <a href={`mailto:${email}`} title={email}
               className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline
                          underline-offset-2 truncate block max-w-[190px]">
              {email}
            </a>
          : <Nil />
        }
      </td>

      {/* 4. founder_number  (show name above, number below) */}
      <td className="px-4 py-3.5 min-w-[140px]">
        {founderName || founderPhone ? (
          <div className="flex flex-col gap-0.5">
            {founderName && (
              <span className="text-sm font-medium text-slate-700 leading-tight">
                {founderName}
              </span>
            )}
            {founderPhone ? (
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="text-xs text-slate-500">{founderPhone}</span>
                <WAButton phone={founderPhone} />
              </div>
            ) : founderName ? (
              <span className="text-xs text-slate-300 italic">no direct line</span>
            ) : null}
          </div>
        ) : <Nil />}
      </td>

      {/* 5. company_number */}
      <td className="px-4 py-3.5 whitespace-nowrap">
        {phone ? (
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="none"
                stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0
                     01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1
                     1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1
                     C9.716 21 3 14.284 3 6V5z" />
              </svg>
              <span className="text-sm text-slate-700">{phone}</span>
            </div>
            <WAButton phone={phone} />
          </div>
        ) : <Nil />}
      </td>

      {/* 6. address */}
      <td className="px-4 py-3.5 max-w-[200px]">
        {address ? (
          <div className="flex items-start gap-1.5">
            <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-0.5" fill="none"
              stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243
                   a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span className="text-sm text-slate-600 leading-snug line-clamp-2">
              {address}
            </span>
          </div>
        ) : <Nil />}
      </td>

      {/* 7. source_url */}
      <td className="px-4 py-3.5 max-w-[170px]">
        {srcUrl ? (
          <a href={srcUrl} target="_blank" rel="noopener noreferrer"
             title={srcUrl}
             className="text-xs text-indigo-500 hover:text-indigo-700 hover:underline
                        underline-offset-2 truncate block max-w-[155px]">
            {shortUrl(srcUrl)}
          </a>
        ) : <Nil />}
      </td>

      {/* 8. last_verified */}
      <td className="px-4 py-3.5 whitespace-nowrap">
        {verified ? (
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
            <span className="text-xs text-slate-600">{verified}</span>
          </div>
        ) : <Nil />}
      </td>

      {/* 9. Status */}
      <td className="px-4 py-3 min-w-[155px]">
        <StatusDropdown
          leadId={lead.id ?? lead.company_name}
          value={status}
          onChange={onStatusChange}
        />
      </td>

      {/* 10. website */}
      <td className="px-4 py-3.5 max-w-[170px]">
        {website ? (
          <a href={website} target="_blank" rel="noopener noreferrer"
             title={website}
             className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline
                        underline-offset-2 truncate block max-w-[155px]">
            {website.replace(/^https?:\/\/(www\.)?/, '')}
          </a>
        ) : <Nil />}
      </td>

      {/* 11. Find Contacts (PDL) */}
      <td className="px-4 py-3.5 whitespace-nowrap">
        {(lead.contacts?.length > 0) ? (
          /* Show inline count badge — click to expand in the contacts drawer */
          <button
            onClick={() => onFindContacts(lead)}
            title="View enriched contacts"
            className="
              inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              bg-emerald-50 text-emerald-700 border border-emerald-200
              hover:bg-emerald-100 hover:border-emerald-300
              active:bg-emerald-200 transition-colors duration-150
              focus:outline-none focus:ring-2 focus:ring-emerald-400 focus:ring-offset-1
            "
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857
                   M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857
                   m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            {lead.contacts.length} contact{lead.contacts.length !== 1 ? 's' : ''}
            {lead.contacts.some(c => c.email) && <span title="Has email">✉</span>}
          </button>
        ) : (
          <button
            onClick={() => onFindContacts(lead)}
            title="Find decision-maker contacts via People Data Labs"
            className="
              inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
              bg-violet-50 text-violet-700 border border-violet-200
              hover:bg-violet-100 hover:border-violet-300 hover:text-violet-800
              active:bg-violet-200 transition-colors duration-150
              focus:outline-none focus:ring-2 focus:ring-violet-400 focus:ring-offset-1
            "
          >
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857
                   M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857
                   m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            Find Contacts
          </button>
        )}
      </td>
    </tr>
  )
}

/* ════════════════════════════════════════════════════════════════════
   TABLE HEADERS — exact same order as columns above
   ════════════════════════════════════════════════════════════════════ */
const HEADERS = [
  // { label, sortable }
  { label: '#',               sortable: false },
  { label: 'Company Name',    sortable: true  },
  { label: 'Email',           sortable: false },
  { label: 'Founder',         sortable: false },
  { label: 'Phone',           sortable: false },
  { label: 'Address',         sortable: false },
  { label: 'Source URL',      sortable: false },
  { label: 'Last Verified',   sortable: false },
  { label: 'Status',          sortable: false },
  { label: 'Website',         sortable: false },
  { label: 'Contacts',        sortable: false },
]

/* ════════════════════════════════════════════════════════════════════
   MAIN EXPORT
   ════════════════════════════════════════════════════════════════════ */
export default function LeadsTable({
  leads,
  isLoading,
  error,
  searchQuery,
  sortDir,
  onSortChange,
}) {
  const isEmpty = !isLoading && !error && leads.length === 0

  // PDL contacts drawer state
  const [activeLead, setActiveLead] = useState(null)
  const pdlHook = usePDLSearch()

  // CRM status per lead — keyed by lead.id or company_name
  // Persisted in component state (survives re-renders, resets on page reload)
  const [statusMap, setStatusMap] = useState({})

  const handleFindContacts = (lead) => setActiveLead(lead)
  const handleClosePDL     = () => { setActiveLead(null); pdlHook.clear() }
  const handleStatusChange = (leadId, newStatus) =>
    setStatusMap(prev => ({ ...prev, [leadId]: newStatus }))

  return (
    <>
      <div className="overflow-hidden rounded-xl border border-slate-200">
        <div className="overflow-x-auto scrollbar-thin">
          <table className="w-full text-left" style={{ minWidth: '1500px' }}>

            {/* ── HEADER ─────────────────────────────────────────────── */}
            <thead>
              <tr className="bg-slate-50 border-b-2 border-slate-200">
                {HEADERS.map(({ label, sortable }) => (
                  <th
                    key={label}
                    className="px-4 py-3.5 text-xs font-bold text-slate-500
                               uppercase tracking-widest whitespace-nowrap"
                  >
                    {sortable ? (
                      <button
                        onClick={onSortChange}
                        className="inline-flex items-center gap-1 hover:text-indigo-600
                                   transition-colors focus:outline-none focus:text-indigo-600"
                      >
                        {label}
                        <SortIcon dir={sortDir} />
                      </button>
                    ) : label}
                  </th>
                ))}
              </tr>
            </thead>

            {/* ── BODY ───────────────────────────────────────────────── */}
            <tbody>
              {isLoading
                ? Array.from({ length: 6 }).map((_, i) => (
                    <SkeletonRow key={i} index={i} />
                  ))
                : leads.map((lead, i) => (
                    <LeadRow
                      key={lead.id ?? `${lead.company_name}-${i}`}
                      lead={lead}
                      index={i}
                      onFindContacts={handleFindContacts}
                      status={statusMap[lead.id ?? lead.company_name] || ''}
                      onStatusChange={handleStatusChange}
                    />
                  ))
              }
            </tbody>
          </table>
        </div>

        {/* Empty state */}
        {isEmpty && (
          searchQuery ? (
            <EmptyState
              icon="search"
              title="No results found."
              description={`No leads match "${searchQuery}". Try clearing the search.`}
            />
          ) : (
            <EmptyState />
          )
        )}

        {/* Footer */}
        {!isLoading && leads.length > 0 && (
          <div className="px-5 py-3 flex items-center justify-between
                          border-t border-slate-100 bg-slate-50/70">
            <span className="text-xs text-slate-500">
              Showing{' '}
              <span className="font-semibold text-slate-700">{leads.length}</span>{' '}
              lead{leads.length !== 1 ? 's' : ''}
            </span>
            <span className="text-xs text-slate-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
              MongoDB · Live data
            </span>
          </div>
        )}
      </div>

      {/* PDL Contacts Drawer — rendered outside the table */}
      {activeLead && (
        <PDLContactsPanel
          lead={activeLead}
          onClose={handleClosePDL}
          hook={pdlHook}
        />
      )}
    </>
  )
}
