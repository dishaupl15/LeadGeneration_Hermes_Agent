import { useState } from 'react'
import EmptyState from './EmptyState'

/* ── Sort icon ──────────────────────────────────────────────────── */
function SortIcon({ direction }) {
  if (!direction) {
    return (
      <svg className="w-3.5 h-3.5 text-slate-400 ml-1 flex-shrink-0" fill="none"
        stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
      </svg>
    )
  }
  return direction === 'asc' ? (
    <svg className="w-3.5 h-3.5 text-indigo-600 ml-1 flex-shrink-0" fill="none"
      stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 15l7-7 7 7" />
    </svg>
  ) : (
    <svg className="w-3.5 h-3.5 text-indigo-600 ml-1 flex-shrink-0" fill="none"
      stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7" />
    </svg>
  )
}

/* ── Shimmer skeleton row ───────────────────────────────────────── */
function SkeletonRow({ index }) {
  const widths = ['w-40', 'w-32', 'w-48', 'w-36', 'w-40', 'w-24']
  return (
    <tr className={index % 2 === 0 ? 'bg-white' : 'bg-slate-50/60'}>
      <td className="px-4 py-3.5">
        <div className="shimmer h-3.5 w-5 rounded" />
      </td>
      {widths.map((w, i) => (
        <td key={i} className="px-5 py-3.5">
          <div className={`shimmer h-3.5 ${w} rounded`} />
        </td>
      ))}
    </tr>
  )
}

/* ── Avatar initials ────────────────────────────────────────────── */
const AVATAR_COLORS = [
  'bg-violet-100 text-violet-700',
  'bg-sky-100 text-sky-700',
  'bg-emerald-100 text-emerald-700',
  'bg-amber-100 text-amber-700',
  'bg-rose-100 text-rose-700',
  'bg-indigo-100 text-indigo-700',
  'bg-teal-100 text-teal-700',
  'bg-pink-100 text-pink-700',
]

function Avatar({ name, index }) {
  const color = AVATAR_COLORS[index % AVATAR_COLORS.length]
  const initials = (name || '?')
    .split(' ')
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join('')
  return (
    <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 ${color}`}>
      {initials || '?'}
    </div>
  )
}

/* ── Format helpers ─────────────────────────────────────────────── */
function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Intl.DateTimeFormat('en-IN', {
      day:   '2-digit',
      month: 'short',
      year:  'numeric',
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function firstOf(arr) {
  // Return first non-empty item from an array, or '—'
  if (!Array.isArray(arr)) return arr || '—'
  const found = arr.find((v) => v && v.trim())
  return found || '—'
}

function buildAddress(lead) {
  const parts = [lead.address, lead.city, lead.state, lead.country].filter(Boolean)
  return parts.join(', ') || '—'
}

/* ── Single data row ────────────────────────────────────────────── */
function LeadRow({ lead, index }) {
  const email   = firstOf(lead.emails)
  const phone   = firstOf(lead.phones)
  const address = buildAddress(lead)

  return (
    <tr
      className={`
        border-b border-slate-100 transition-colors duration-100 cursor-default
        ${index % 2 === 0 ? 'bg-white' : 'bg-slate-50/40'}
        hover:bg-indigo-50/50
      `}
    >
      {/* # */}
      <td className="px-4 py-3.5 text-xs text-slate-400 font-medium">{index + 1}</td>

      {/* Company Name */}
      <td className="px-5 py-3.5">
        <div className="flex items-center gap-3">
          <Avatar name={lead.company_name} index={index} />
          <p className="text-sm font-semibold text-slate-800 leading-tight line-clamp-2 max-w-[180px]">
            {lead.company_name || '—'}
          </p>
        </div>
      </td>

      {/* Website */}
      <td className="px-5 py-3.5 max-w-[180px]">
        {lead.website ? (
          <a
            href={lead.website}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline underline-offset-2
                       transition-colors truncate block max-w-[160px]"
            title={lead.website}
          >
            {lead.website.replace(/^https?:\/\/(www\.)?/, '')}
          </a>
        ) : (
          <span className="text-sm text-slate-400">—</span>
        )}
      </td>

      {/* Email */}
      <td className="px-5 py-3.5 max-w-[200px]">
        {email !== '—' ? (
          <a
            href={`mailto:${email}`}
            className="text-sm text-indigo-600 hover:text-indigo-800 hover:underline underline-offset-2
                       transition-colors truncate block max-w-[180px]"
            title={email}
          >
            {email}
          </a>
        ) : (
          <span className="text-sm text-slate-400">—</span>
        )}
      </td>

      {/* Phone */}
      <td className="px-5 py-3.5">
        <div className="flex items-center gap-1.5">
          {phone !== '—' && (
            <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" fill="none"
              stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257
                   1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1
                   1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
            </svg>
          )}
          <span className="text-sm text-slate-700 whitespace-nowrap">{phone}</span>
        </div>
      </td>

      {/* Address */}
      <td className="px-5 py-3.5 max-w-[200px]">
        <div className="flex items-start gap-1.5">
          {address !== '—' && (
            <svg className="w-3.5 h-3.5 text-slate-400 flex-shrink-0 mt-0.5" fill="none"
              stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0
                   1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          )}
          <span className="text-sm text-slate-600 leading-snug line-clamp-2">{address}</span>
        </div>
      </td>

      {/* Created At */}
      <td className="px-5 py-3.5 whitespace-nowrap">
        <span className="text-xs text-slate-500">{formatDate(lead.created_at)}</span>
      </td>
    </tr>
  )
}

/* ── Main table component ───────────────────────────────────────── */
/**
 * Props:
 *   leads       – MongoLeadDoc[]  (from MongoDB via backend)
 *   isLoading   – boolean
 *   error       – string | null
 *   searchQuery – string          – filter by company name
 *   sortDir     – 'asc' | 'desc' | null
 *   onSortChange – () => void     – toggle sort direction
 */
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
        <table className="w-full text-left min-w-[900px]">

          {/* ── Header ── */}
          <thead>
            <tr className="bg-slate-50 border-b-2 border-slate-200">

              {/* # */}
              <th className="w-10 px-4 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-widest">
                #
              </th>

              {/* Company Name — sortable */}
              <th className="w-52 px-5 py-3.5">
                <button
                  onClick={onSortChange}
                  className="inline-flex items-center gap-1 text-xs font-bold text-slate-500
                             uppercase tracking-widest hover:text-indigo-600 transition-colors
                             focus:outline-none focus:text-indigo-600"
                >
                  Company Name
                  <SortIcon direction={sortDir} />
                </button>
              </th>

              {/* Static headers */}
              {['Website', 'Email', 'Phone', 'Address', 'Created At'].map((label) => (
                <th key={label}
                  className="px-5 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-widest whitespace-nowrap">
                  {label}
                </th>
              ))}
            </tr>
          </thead>

          {/* ── Body ── */}
          <tbody>
            {isLoading
              ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} index={i} />)
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

      {/* Empty / search-no-results state */}
      {isEmpty && (
        searchQuery ? (
          <EmptyState
            icon="search"
            title="No results found."
            description={`No leads match "${searchQuery}". Try a different name or clear the search.`}
          />
        ) : (
          <EmptyState />
        )
      )}

      {/* Footer count */}
      {!isLoading && leads.length > 0 && (
        <div className="px-5 py-3 flex items-center justify-between border-t border-slate-100 bg-slate-50/70">
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
