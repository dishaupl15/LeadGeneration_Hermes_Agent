import EmptyState from './EmptyState'

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

/** Sort icon for Company Name header */
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
  // 10 columns: #, Company, Email, Founder Ph, Company Ph, Address, Source, Verified, Confidence, Website
  const ws = ['w-5','w-44','w-44','w-28','w-28','w-44','w-32','w-24','w-20','w-32']
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
   ════════════════════════════════════════════════════════════════════ */
function LeadRow({ lead, index }) {
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
            {founderPhone
              ? <span className="text-xs text-slate-500">{founderPhone}</span>
              : founderName
                ? <span className="text-xs text-slate-300 italic">no direct line</span>
                : null
            }
          </div>
        ) : <Nil />}
      </td>

      {/* 5. company_number */}
      <td className="px-4 py-3.5 whitespace-nowrap">
        {phone ? (
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

      {/* 9. confidence */}
      <td className="px-4 py-3.5 min-w-[90px]">
        <ConfidenceBar value={confidence} />
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
  { label: 'Confidence',      sortable: false },
  { label: 'Website',         sortable: false },
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

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full text-left" style={{ minWidth: '1380px' }}>

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
  )
}
