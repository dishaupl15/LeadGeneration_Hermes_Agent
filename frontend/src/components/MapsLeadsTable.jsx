/**
 * MapsLeadsTable
 *
 * Displays businesses returned by the Google Maps → enrichment pipeline.
 * Each row is expandable to show people-enrichment contacts (PDL → Prospeo →
 * ContactOut waterfall).
 *
 * Columns: # | Business Name | Address | Phone | Website | Type | Maps Link | Area
 * Expandable: Contacts from people-enrichment orchestrator
 */

import { useState } from 'react'

/* ── helpers ──────────────────────────────────────────────────────────────── */
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

function humanType(t) {
  if (!t) return null
  return t.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/* ── atoms ─────────────────────────────────────────────────────────────────── */
function Nil() {
  return <span className="text-xs text-slate-300 italic">—</span>
}

const AVATAR_COLORS = [
  'bg-emerald-100 text-emerald-700', 'bg-sky-100 text-sky-700',
  'bg-violet-100 text-violet-700',   'bg-amber-100 text-amber-700',
  'bg-rose-100 text-rose-700',       'bg-teal-100 text-teal-700',
  'bg-indigo-100 text-indigo-700',   'bg-pink-100 text-pink-700',
]
function Avatar({ name, index }) {
  const color    = AVATAR_COLORS[index % AVATAR_COLORS.length]
  const initials = (name || '?').split(' ').slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '').join('') || '?'
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center
                     text-xs font-bold flex-shrink-0 ${color}`}>
      {initials}
    </div>
  )
}

/* ── contact source badge ─────────────────────────────────────────────────── */
const SOURCE_COLORS = {
  pdl:        'bg-blue-50 text-blue-700 border-blue-200',
  prospeo:    'bg-violet-50 text-violet-700 border-violet-200',
  contactout: 'bg-amber-50 text-amber-700 border-amber-200',
}
function SourceBadge({ source }) {
  const cls = SOURCE_COLORS[source] || 'bg-slate-50 text-slate-600 border-slate-200'
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px]
                      font-semibold border uppercase tracking-wide ${cls}`}>
      {source}
    </span>
  )
}

/* ── single contact card ──────────────────────────────────────────────────── */
function ContactCard({ contact, index }) {
  const name  = (contact.name  || '').trim()
  const title = (contact.title || '').trim()
  const email = (contact.email || '').trim()
  const phone = (contact.phone || '').trim()
  const li    = (contact.linkedin_url || '').trim()
  const sources    = Array.isArray(contact.sources) ? contact.sources : []
  const confidence = typeof contact.confidence === 'number'
    ? Math.round(contact.confidence * 100)
    : null

  // Only show contacts with a real name and at least one data point
  if (!name) return null

  const confColor =
    confidence >= 75 ? 'text-emerald-600' :
    confidence >= 50 ? 'text-amber-600'   : 'text-slate-400'

  return (
    <div className="flex items-start gap-3 p-3 rounded-lg bg-white border border-slate-100
                    shadow-sm hover:border-slate-200 transition-colors">
      {/* index circle */}
      <div className="w-5 h-5 rounded-full bg-slate-100 flex items-center justify-center
                      text-[10px] font-bold text-slate-500 flex-shrink-0 mt-0.5">
        {index + 1}
      </div>

      <div className="flex-1 min-w-0">
        {/* name + title */}
        <p className="text-sm font-semibold text-slate-800 leading-tight truncate">{name}</p>
        {title && (
          <p className="text-xs text-slate-500 mt-0.5 truncate">{title}</p>
        )}

        {/* contact details */}
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
          {email && (
            <a href={`mailto:${email}`}
               className="inline-flex items-center gap-1 text-xs text-indigo-600
                          hover:text-indigo-800 hover:underline underline-offset-2 truncate max-w-[200px]"
               title={email}>
              <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7
                     a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
              </svg>
              {email}
            </a>
          )}
          {phone && (
            <a href={`tel:${phone}`}
               className="inline-flex items-center gap-1 text-xs text-slate-600
                          hover:text-slate-800 whitespace-nowrap">
              <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0
                     01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13
                     -2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19
                     a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
              </svg>
              {phone}
            </a>
          )}
          {li && (
            <a href={li} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-xs text-sky-600
                          hover:text-sky-800 whitespace-nowrap">
              <svg className="w-3 h-3 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037
                         -1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046
                         c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286z
                         M5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065z
                         m1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542
                         C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729
                         C24 .774 23.2 0 22.222 0h.003z"/>
              </svg>
              LinkedIn
            </a>
          )}
        </div>
      </div>

      {/* sources + confidence */}
      <div className="flex flex-col items-end gap-1 flex-shrink-0">
        <div className="flex gap-1 flex-wrap justify-end">
          {sources.map((s) => <SourceBadge key={s} source={s} />)}
        </div>
        {confidence !== null && (
          <span className={`text-[10px] font-semibold ${confColor}`}>
            {confidence}%
          </span>
        )}
      </div>
    </div>
  )
}

/* ── contacts panel (expanded row) ──────────────────────────────────────────── */
function ContactsPanel({ contacts, colSpan }) {
  // Filter out contacts with no name
  const valid = (contacts || []).filter((c) => (c.name || '').trim())
  if (valid.length === 0) return null

  return (
    <tr className="bg-slate-50/80">
      <td colSpan={colSpan} className="px-4 pb-4 pt-0">
        <div className="mt-1 pl-11">
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">
            Decision-Maker Contacts ({valid.length})
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {valid.map((contact, i) => (
              <ContactCard key={i} contact={contact} index={i} />
            ))}
          </div>
        </div>
      </td>
    </tr>
  )
}

/* ── skeleton row ────────────────────────────────────────────────────────── */
function SkeletonRow({ index }) {
  const ws = ['w-5','w-44','w-44','w-28','w-32','w-24','w-24','w-28']
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

/* ── data row ────────────────────────────────────────────────────────────── */
function BizRow({ biz, index, colSpan }) {
  const [expanded, setExpanded] = useState(false)

  const name    = (biz.name || '').trim() || '—'
  const address = (biz.address || '').trim() || null
  const phone   = (biz.phone || '').trim() || null
  const website = (biz.website || '').trim() || null
  const mapsUri = (biz.google_maps_uri || '').trim() || null
  const type    = humanType(biz.primary_type)
  const area    = (biz.search_area || '').trim() || null

  // Contacts from the people-enrichment orchestrator
  const contacts = Array.isArray(biz.contacts) ? biz.contacts : []
  const validContacts = contacts.filter((c) => (c.name || '').trim())
  const hasContacts = validContacts.length > 0

  const rowBg = index % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'
  const expandedBg = 'bg-slate-50/80'

  return (
    <>
      <tr className={`border-b border-slate-100 transition-colors duration-100
                      ${expanded ? expandedBg : rowBg} hover:bg-emerald-50/40`}>

        {/* 1. # */}
        <td className="px-4 py-3.5 text-xs text-slate-400 font-medium w-10">
          {index + 1}
        </td>

        {/* 2. Business name + contacts toggle */}
        <td className="px-4 py-3.5">
          <div className="flex items-center gap-3">
            <Avatar name={name} index={index} />
            <div className="flex-1 min-w-0">
              <span className="text-sm font-semibold text-slate-800 leading-tight
                               line-clamp-2 max-w-[180px] block">
                {name}
              </span>
              {/* contacts toggle chip */}
              {hasContacts && (
                <button
                  onClick={() => setExpanded((v) => !v)}
                  className={`mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                              text-[10px] font-semibold border transition-colors cursor-pointer
                              ${expanded
                                ? 'bg-indigo-100 text-indigo-700 border-indigo-200'
                                : 'bg-slate-100 text-slate-500 border-slate-200 hover:bg-indigo-50 hover:text-indigo-600 hover:border-indigo-200'
                              }`}
                >
                  <svg className={`w-2.5 h-2.5 transition-transform ${expanded ? 'rotate-180' : ''}`}
                    fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                      d="M19 9l-7 7-7-7"/>
                  </svg>
                  {validContacts.length} contact{validContacts.length !== 1 ? 's' : ''}
                  {contacts.some(c => c.email) && (
                    <span className="text-emerald-600 ml-0.5">✉</span>
                  )}
                  {contacts.some(c => c.phone) && (
                    <span className="text-emerald-600">📞</span>
                  )}
                </button>
              )}
              {!hasContacts && (
                <span className="mt-1 inline-flex items-center px-1.5 py-0.5 rounded
                                 text-[10px] text-slate-300 italic">
                  no contacts
                </span>
              )}
            </div>
          </div>
        </td>

        {/* 3. Address */}
        <td className="px-4 py-3.5 max-w-[220px]">
          {address ? (
            <div className="flex items-start gap-1.5">
              <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-0.5"
                fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827
                     0l-4.244-4.243a8 8 0 1111.314 0z"/>
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
              </svg>
              <span className="text-xs text-slate-600 leading-snug line-clamp-3">
                {address}
              </span>
            </div>
          ) : <Nil />}
        </td>

        {/* 4. Phone */}
        <td className="px-4 py-3.5 whitespace-nowrap">
          {phone ? (
            <div className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0"
                fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0
                     01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13
                     -2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2
                     0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
              </svg>
              <a href={`tel:${phone}`}
                 className="text-sm text-slate-700 hover:text-indigo-600 transition-colors">
                {phone}
              </a>
            </div>
          ) : <Nil />}
        </td>

        {/* 5. Website */}
        <td className="px-4 py-3.5 max-w-[180px]">
          {website ? (
            <a href={website} target="_blank" rel="noopener noreferrer"
               title={website}
               className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline
                          underline-offset-2 truncate block max-w-[165px]">
              {shortUrl(website)}
            </a>
          ) : <Nil />}
        </td>

        {/* 6. Type */}
        <td className="px-4 py-3.5">
          {type ? (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full
                             text-xs font-medium bg-slate-100 text-slate-600
                             border border-slate-200 whitespace-nowrap">
              {type}
            </span>
          ) : <Nil />}
        </td>

        {/* 7. Google Maps */}
        <td className="px-4 py-3.5">
          {mapsUri ? (
            <a href={mapsUri} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg
                          text-xs font-medium text-emerald-700 bg-emerald-50
                          border border-emerald-200 hover:bg-emerald-100
                          transition-colors whitespace-nowrap">
              <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none"
                stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14
                     4h6m0 0v6m0-6L10 14"/>
              </svg>
              View on Maps
            </a>
          ) : <Nil />}
        </td>

        {/* 8. Search area */}
        <td className="px-4 py-3.5 whitespace-nowrap">
          {area ? (
            <span className="text-xs text-slate-500">{area}</span>
          ) : <Nil />}
        </td>
      </tr>

      {/* Expanded contacts row */}
      {expanded && hasContacts && (
        <ContactsPanel contacts={validContacts} colSpan={colSpan} />
      )}
    </>
  )
}

/* ── stats bar ──────────────────────────────────────────────────────────── */
function StatsBar({ stats, total }) {
  if (!stats) return null

  return (
    <div className="border-t border-slate-100">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 py-3
                      text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"/>
          <strong className="text-slate-700">{total}</strong> unique businesses
        </span>
        <span>📞 {stats.with_phone} with phone</span>
        <span>🌐 {stats.with_website} with website</span>
        <span>🔍 {stats.queries_executed} queries</span>
        <span>📊 {stats.total_raw_results} raw results</span>
        {stats.duplicates_removed + (stats.secondary_dupes ?? 0) > 0 && (
          <span>🔄 {stats.duplicates_removed + (stats.secondary_dupes ?? 0)} dupes removed</span>
        )}
        <span>⏱ {stats.elapsed_seconds}s</span>
        {stats.target_reached && (
          <span className="text-emerald-600 font-semibold">✓ Target reached</span>
        )}
        {stats.exhausted && (
          <span className="text-amber-600 font-semibold">⚠ Areas exhausted</span>
        )}
      </div>
    </div>
  )
}

/* ── main export ─────────────────────────────────────────────────────────── */
const HEADERS = [
  '#', 'Business Name', 'Address', 'Phone', 'Website', 'Type', 'Google Maps', 'Search Area',
]

export default function MapsLeadsTable({ businesses, isLoading, searchQuery, stats }) {
  const filtered = searchQuery
    ? businesses.filter((b) =>
        (b.name ?? '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (b.address ?? '').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : businesses

  const isEmpty = !isLoading && filtered.length === 0
  const colSpan = HEADERS.length

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="overflow-x-auto scrollbar-thin">
        <table className="w-full text-left" style={{ minWidth: '1100px' }}>
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">
              {HEADERS.map((h) => (
                <th key={h} className="px-4 py-3.5 text-xs font-bold text-slate-500
                                       uppercase tracking-widest whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} index={i} />)
              : filtered.map((biz, i) => (
                  <BizRow
                    key={biz.place_id ?? `${biz.name}-${i}`}
                    biz={biz}
                    index={i}
                    colSpan={colSpan}
                  />
                ))
            }
          </tbody>
        </table>
      </div>

      {isEmpty && (
        <div className="py-16 flex flex-col items-center gap-3 text-slate-400">
          <svg className="w-12 h-12 opacity-30" fill="none"
            stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9
                 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1
                 0 00-.553-.894L15 4m0 13V4m0 0L9 7"/>
          </svg>
          <p className="text-sm font-medium">
            {searchQuery ? `No results match "${searchQuery}"` : 'No businesses found yet.'}
          </p>
          <p className="text-xs">
            {searchQuery
              ? 'Try clearing the search or broadening your filters.'
              : 'Select a category, state, and click Search to discover businesses.'}
          </p>
        </div>
      )}

      {/* Stats footer */}
      {!isLoading && businesses.length > 0 && (
        <StatsBar stats={stats} total={filtered.length} />
      )}
    </div>
  )
}
