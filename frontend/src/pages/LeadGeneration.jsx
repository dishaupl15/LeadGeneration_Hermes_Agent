import { useState, useMemo, useEffect, useCallback } from 'react'
import CategoryScroller from '../components/CategoryScroller'
import RefreshLeadsButton from '../components/RefreshLeadsButton'
import LeadsTable from '../components/LeadsTable'
import ErrorBanner from '../components/ErrorBanner'
import HistoryPanel from '../components/HistoryPanel'
import FollowUpsPanel from '../components/FollowUpsPanel'
import { useGenerateLeads } from '../hooks/useGenerateLeads'
import { getMapsStates, getMapsDistricts, getLeadStatusCounts, getLeads, buildExportUrl, bulkEnrichOrigami } from '../services/api'
import OrigamiStatsPanel from '../components/OrigamiStatsPanel'

/* ── Geography + Target selector ───────────────────────────────────────── */
function GeoSelector({
  selectedState, selectedDistrict, target,
  onStateChange, onDistrictChange, onTargetChange,
}) {
  const [states,           setStates]           = useState([])
  const [districts,        setDistricts]        = useState([])
  const [loadingStates,    setLoadingStates]    = useState(false)
  const [loadingDistricts, setLoadingDistricts] = useState(false)

  useEffect(() => {
    setLoadingStates(true)
    getMapsStates()
      .then((d) => setStates(d.states ?? []))
      .catch(() => setStates([]))
      .finally(() => setLoadingStates(false))
  }, [])

  useEffect(() => {
    if (!selectedState) { setDistricts([]); onDistrictChange(''); return }
    setLoadingDistricts(true)
    onDistrictChange('')
    getMapsDistricts(selectedState)
      .then((d) => setDistricts(d.districts ?? []))
      .catch(() => setDistricts([]))
      .finally(() => setLoadingDistricts(false))
  }, [selectedState]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="crm-card p-5 mb-6">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4 px-0.5">
        Location &amp; Target
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

        {/* State */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            State <span className="text-rose-400">*</span>
          </label>
          <div className="relative">
            {loadingStates && (
              <div className="absolute inset-y-0 right-9 flex items-center pr-1">
                <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              </div>
            )}
            <select
              value={selectedState}
              onChange={(e) => onStateChange(e.target.value)}
              disabled={loadingStates}
              className="crm-input pr-9 appearance-none disabled:opacity-60 disabled:cursor-wait"
            >
              <option value="">— Select state —</option>
              {states.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
              <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </div>
        </div>

        {/* District */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            District <span className="ml-1 text-slate-400 font-normal">(optional)</span>
          </label>
          <div className="relative">
            {loadingDistricts && (
              <div className="absolute inset-y-0 right-9 flex items-center pr-1">
                <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>
              </div>
            )}
            <select
              value={selectedDistrict}
              onChange={(e) => onDistrictChange(e.target.value)}
              disabled={!selectedState || loadingDistricts}
              className="crm-input pr-9 appearance-none disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="">— All districts —</option>
              {districts.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
              <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </div>
        </div>

        {/* Target */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">Target companies</label>
          <div className="relative">
            <select
              value={target}
              onChange={(e) => onTargetChange(Number(e.target.value))}
              className="crm-input pr-9 appearance-none"
            >
              {[10, 20, 30, 50, 75, 100, 150, 200].map((n) => (
                <option key={n} value={n}>{n} companies</option>
              ))}
            </select>
            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
              <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </div>
        </div>
      </div>

      {selectedState && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full
                           bg-indigo-50 border border-indigo-200 text-indigo-700 text-xs font-semibold">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            {selectedDistrict ? `${selectedDistrict}, ${selectedState}` : `${selectedState} (all districts)`}
          </span>
          <span className="text-xs text-slate-400">· Google Maps discovery · target {target} companies</span>
        </div>
      )}
    </div>
  )
}

/* ── Generate button ────────────────────────────────────────────────────── */
function GenerateLeadsButton({ ready, isLoading, onClick, selectedCategory }) {
  const disabled = !ready || isLoading
  return (
    <div className="flex flex-col items-center gap-3 mb-8">
      {!ready && (
        <p className="text-sm text-slate-400 italic">
          {!selectedCategory ? '📂 Select an industry category above' : '📍 Select a state to enable discovery'}
        </p>
      )}
      <button
        onClick={onClick}
        disabled={disabled}
        className={`
          inline-flex items-center justify-center gap-2.5
          px-12 py-4 rounded-xl text-lg font-semibold text-white
          shadow-md transition-all duration-200 relative overflow-hidden group
          ${disabled
            ? 'bg-indigo-400 opacity-60 cursor-not-allowed pointer-events-none'
            : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 hover:shadow-lg cursor-pointer'
          }
        `}
      >
        {!disabled && (
          <span className="absolute inset-0 bg-white/15 translate-x-[-100%]
                           group-hover:translate-x-[100%] transition-transform
                           duration-700 ease-in-out skew-x-[-15deg] pointer-events-none"/>
        )}
        {isLoading ? (
          <>
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            Generating leads…
          </>
        ) : (
          <>
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                d="M13 10V3L4 14h7v7l9-11h-7z"/>
            </svg>
            Generate Leads
            {selectedCategory && (
              <span className="text-sm font-normal text-indigo-200">— {selectedCategory}</span>
            )}
          </>
        )}
      </button>
      {isLoading ? (
        <div className="flex flex-col items-center gap-1">
          <p className="text-xs text-indigo-500 animate-pulse font-medium">⏳ Discovering companies from Google Maps…</p>
          <p className="text-xs text-slate-400">Then enriching via CompanyEnrich → Serper → Firecrawl</p>
        </div>
      ) : (
        <p className="text-xs text-slate-400">Powered by Google Maps · CompanyEnrich · Serper · Firecrawl</p>
      )}
    </div>
  )
}

/* ── Pipeline stats bar ─────────────────────────────────────────────────── */
function PipelineStatsBar({ stats }) {
  if (!stats) return null
  const discovered     = stats.google_maps_discovered  ?? 0
  const finalValid     = stats.final_valid_companies   ?? discovered
  const dupes          = stats.google_maps_duplicates  ?? 0
  const elapsed        = stats.elapsed_seconds         ?? null
  const peopleContacts = stats.people_contacts_found   ?? 0
  const peopleEmails   = stats.people_emails_found     ?? 0

  return (
    <div className="mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3
                    rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-500">
      <span className="flex items-center gap-1.5 font-semibold text-slate-600">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0"/>
        Pipeline
      </span>
      <span>🗺️ Discovered: <strong className="text-slate-700">{discovered}</strong></span>
      {dupes > 0 && <span>🔄 Dupes: <strong>{dupes}</strong></span>}
      <span>✅ Saved: <strong className="text-slate-700">{finalValid}</strong></span>
      {(peopleContacts > 0 || peopleEmails > 0) && (
        <>
          <span className="text-slate-300">|</span>
          <span>👥 Contacts: <strong className="text-indigo-600">{peopleContacts}</strong></span>
          {peopleEmails > 0 && (
            <span>✉ Emails: <strong className="text-emerald-600">{peopleEmails}</strong></span>
          )}
        </>
      )}
      {elapsed != null && (
        <><span className="text-slate-300">|</span><span>⏱ <strong>{elapsed}s</strong></span></>
      )}
    </div>
  )
}

/* ── Stat card ──────────────────────────────────────────────────────────── */
function StatCard({ label, value, icon, color }) {
  return (
    <div className="crm-card p-5 flex items-center gap-4">
      <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${color}`}>{icon}</div>
      <div>
        <p className="text-2xl font-bold text-slate-800">{value}</p>
        <p className="text-xs text-slate-500 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

/* ── Tab bar + search + date filters (server-driven) ────────────────────── */
/**
 * LeadsExplorer: a self-contained panel that owns its own query state.
 * It fetches from GET /leads with tab + search + date_from + date_to params.
 * Counts come from GET /leads/status-counts.
 *
 * Tabs: New Leads | Old Untouched | Interested | Not Interested | Follow-ups | All Leads
 */
function LeadsExplorer({ category, refreshTrigger, onStatusUpdate, onLeadUpdate }) {
  const [activeTab,  setActiveTab]  = useState('all')
  const [search,     setSearch]     = useState('')
  const [dateFrom,   setDateFrom]   = useState('')
  const [dateTo,     setDateTo]     = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // Leads query state
  const [leads,    setLeads]    = useState([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState('')
  const PER_PAGE = 50

  // Tab counts
  const [counts,        setCounts]        = useState({})
  const [countsLoading, setCountsLoading] = useState(false)

  // Debounce search input (300 ms) so we don't fire on every keystroke
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  // Re-fetch counts when category, refreshTrigger, or tab changes
  useEffect(() => {
    let cancelled = false
    setCountsLoading(true)
    getLeadStatusCounts(category || null)
      .then(res => { if (!cancelled) setCounts(res.counts ?? {}) })
      .catch(() => { if (!cancelled) setCounts({}) })
      .finally(() => { if (!cancelled) setCountsLoading(false) })
    return () => { cancelled = true }
  }, [category, refreshTrigger])

  // Re-fetch leads whenever any filter changes
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    const params = {
      ...(category  ? { category } : {}),
      tab:       activeTab,
      page,
      per_page:  PER_PAGE,
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(dateFrom        ? { date_from: dateFrom }     : {}),
      ...(dateTo          ? { date_to:   dateTo }       : {}),
    }
    getLeads(params)
      .then(res => {
        if (!cancelled) {
          setLeads(res.leads ?? [])
          setTotal(res.total ?? 0)
        }
      })
      .catch(err => { if (!cancelled) setError(err.message || 'Failed to load leads.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [category, activeTab, page, debouncedSearch, dateFrom, dateTo, refreshTrigger])

  // Reset to page 1 when filters change (but not page itself)
  useEffect(() => { setPage(1) }, [category, activeTab, debouncedSearch, dateFrom, dateTo])

  const TABS = [
    { key: 'new_leads',      label: 'New Leads',      countKey: 'new',           dot: 'bg-sky-400',     active: 'bg-sky-600 text-white border-sky-600',                       inactive: 'bg-white text-sky-700 border-sky-200 hover:bg-sky-50' },
    { key: 'old_untouched',  label: 'Old Untouched',  countKey: 'old_untouched', dot: 'bg-orange-400',  active: 'bg-orange-500 text-white border-orange-500',                 inactive: 'bg-white text-orange-700 border-orange-200 hover:bg-orange-50' },
    { key: 'interested',     label: 'Interested',     countKey: 'interested',    dot: 'bg-emerald-400', active: 'bg-emerald-600 text-white border-emerald-600',               inactive: 'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50' },
    { key: 'not_interested', label: 'Not Interested', countKey: 'not_interested',dot: 'bg-rose-400',    active: 'bg-rose-600 text-white border-rose-600',                     inactive: 'bg-white text-rose-700 border-rose-200 hover:bg-rose-50' },
    { key: 'follow_ups',     label: 'Follow-ups',     countKey: 'follow_ups',    dot: 'bg-indigo-400',  active: 'bg-indigo-600 text-white border-indigo-600',                 inactive: 'bg-white text-indigo-700 border-indigo-200 hover:bg-indigo-50' },
    { key: 'all',            label: 'All Leads',      countKey: 'total',         dot: 'bg-slate-400',   active: 'bg-slate-800 text-white border-slate-800',                   inactive: 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50' },
  ]

  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE))

  return (
    <div className="crm-card p-5 sm:p-6 mt-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
          <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M4 6h16M4 10h16M4 14h16M4 18h16"/>
          </svg>
          All Leads
          {!countsLoading && (
            <span className="text-xs font-normal text-slate-400">
              — {counts.total ?? 0} total
            </span>
          )}
        </h2>

        {/* Export buttons */}
        <div className="flex items-center gap-2">
          <a
            href={buildExportUrl('csv', {
              ...(category ? { category } : {}),
              ...(activeTab !== 'all' ? { tab: activeTab } : {}),
              ...(debouncedSearch ? { search: debouncedSearch } : {}),
              ...(dateFrom ? { date_from: dateFrom } : {}),
              ...(dateTo   ? { date_to:   dateTo }   : {}),
            })}
            download
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                       bg-emerald-50 text-emerald-700 border border-emerald-200
                       hover:bg-emerald-100 hover:border-emerald-300 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-emerald-400"
            title="Download filtered leads as CSV"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
            </svg>
            CSV
          </a>
          <a
            href={buildExportUrl('excel', {
              ...(category ? { category } : {}),
              ...(activeTab !== 'all' ? { tab: activeTab } : {}),
              ...(debouncedSearch ? { search: debouncedSearch } : {}),
              ...(dateFrom ? { date_from: dateFrom } : {}),
              ...(dateTo   ? { date_to:   dateTo }   : {}),
            })}
            download
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                       bg-indigo-50 text-indigo-700 border border-indigo-200
                       hover:bg-indigo-100 hover:border-indigo-300 transition-colors
                       focus:outline-none focus:ring-2 focus:ring-indigo-400"
            title="Download filtered leads as Excel"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
            </svg>
            Excel
          </a>
        </div>
      </div>

      {/* ── Tab bar ── */}
      <div className="flex flex-wrap gap-2 mb-4">
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
                        border transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-indigo-400
                        ${activeTab === tab.key ? tab.active : tab.inactive}`}
          >
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
              activeTab === tab.key ? 'bg-white/80' : tab.dot
            }`}/>
            {tab.label}
            <span className={`inline-flex items-center justify-center min-w-[18px] h-4 px-1 rounded-full
                              text-[10px] font-bold
                              ${activeTab === tab.key ? 'bg-white/20 text-white' : 'bg-slate-100 text-slate-600'}
                              ${countsLoading ? 'opacity-40' : ''}`}>
              {countsLoading ? '…' : (counts[tab.countKey] ?? 0)}
            </span>
          </button>
        ))}
      </div>

      {/* ── Search + Date filters ── */}
      <div className="flex flex-wrap gap-3 mb-4">

        {/* Search */}
        <div className="relative flex-1 min-w-[220px]">
          <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
            <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
          </div>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search name, email, phone, company…"
            className="crm-input pl-9 pr-8 text-sm w-full"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute inset-y-0 right-0 flex items-center pr-2.5
                         text-slate-400 hover:text-slate-600"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          )}
        </div>

        {/* Date From */}
        <div className="flex flex-col gap-0.5 min-w-[130px]">
          <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider pl-0.5">
            From
          </label>
          <input
            type="date"
            value={dateFrom}
            onChange={e => setDateFrom(e.target.value)}
            className="crm-input text-sm"
          />
        </div>

        {/* Date To */}
        <div className="flex flex-col gap-0.5 min-w-[130px]">
          <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider pl-0.5">
            To
          </label>
          <input
            type="date"
            value={dateTo}
            onChange={e => setDateTo(e.target.value)}
            className="crm-input text-sm"
          />
        </div>

        {/* Clear filters */}
        {(search || dateFrom || dateTo) && (
          <button
            onClick={() => { setSearch(''); setDateFrom(''); setDateTo('') }}
            className="self-end mb-0.5 inline-flex items-center gap-1 px-3 py-2 rounded-lg
                       text-xs font-semibold text-slate-500 bg-slate-100 hover:bg-slate-200
                       transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
            </svg>
            Clear
          </button>
        )}
      </div>

      {/* ── Error ── */}
      {error && (
        <p className="text-sm text-rose-600 mb-3">{error}</p>
      )}

      {/* ── Table ── */}
      <LeadsTable
        leads={leads}
        isLoading={loading}
        searchQuery={debouncedSearch}
        onStatusUpdate={(leadId, newStatus, updatedDoc) => {
          // Update in local list immediately
          setLeads(prev => prev.map(l => {
            const id = l.id ?? l._id
            return id === leadId
              ? (updatedDoc ? { ...l, ...updatedDoc, id: leadId } : { ...l, status: newStatus })
              : l
          }))
          // Refresh counts
          if (onStatusUpdate) onStatusUpdate(leadId, newStatus, updatedDoc)
        }}
        onLeadUpdate={(updatedDoc) => {
          if (!updatedDoc) return
          const uid = updatedDoc.id ?? updatedDoc._id
          setLeads(prev => prev.map(l => (l.id ?? l._id) === uid ? { ...l, ...updatedDoc } : l))
          if (onLeadUpdate) onLeadUpdate(updatedDoc)
        }}
      />

      {/* ── Pagination ── */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-100">
          <span className="text-xs text-slate-500">
            Page <strong>{page}</strong> of <strong>{totalPages}</strong>
            {' '}·{' '}<strong>{total}</strong> lead{total !== 1 ? 's' : ''}
          </span>
          <div className="flex gap-1.5">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-200
                         bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40
                         disabled:cursor-not-allowed transition-colors"
            >
              ← Prev
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-200
                         bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40
                         disabled:cursor-not-allowed transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* ── Footer count ── */}
      {!loading && leads.length > 0 && totalPages === 1 && (
        <div className="mt-3 pt-2 border-t border-slate-100 flex items-center justify-between">
          <span className="text-xs text-slate-400">
            Showing <strong className="text-slate-600">{leads.length}</strong> of{' '}
            <strong className="text-slate-600">{total}</strong> leads
          </span>
          <span className="text-xs text-slate-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"/>
            MongoDB · Live
          </span>
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════════════════ */
export default function LeadGeneration() {
  // ── UI state ──────────────────────────────────────────────────────────────
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedState,    setSelectedState]    = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  const [target,           setTarget]           = useState(10)
  const [sortDir,          setSortDir]          = useState(null)
  const [showHistory,      setShowHistory]      = useState(false)
  const [showFollowUps,    setShowFollowUps]    = useState(false)

  // Bumped after status/note/follow-up changes to re-fetch counts & explorer
  const [refreshTick, setRefreshTick] = useState(0)

  // Origami bulk enrichment state
  const [bulkOrigamiRunning, setBulkOrigamiRunning] = useState(false)
  const [bulkOrigamiResult,  setBulkOrigamiResult]  = useState(null)  // null | { succeeded, failed, founders_found, origami_enriched }
  const [bulkOrigamiError,   setBulkOrigamiError]   = useState('')
  const [origamiStatsTick,   setOrigamiStatsTick]   = useState(0)     // bump to refresh OrigamiStatsPanel

  // History-override: when user clicks "Load into table" in the history panel
  const [historyLeads, setHistoryLeads] = useState(null)
  const [historyLabel, setHistoryLabel] = useState('')

  // ── Lead generation hook ─────────────────────────────────────────────────
  const {
    leads, isLoading, isRefreshing, error, pipelineStats,
    generate, refreshFromDB, clear,
  } = useGenerateLeads()

  // Which leads to show in the "Generated Results" panel
  const activeLeads = historyLeads !== null ? historyLeads : leads

  // ── Callbacks from LeadsExplorer / generated table ───────────────────────
  const handleStatusUpdate = useCallback((leadId, newStatus, updatedLeadDoc) => {
    if (historyLeads !== null) {
      setHistoryLeads(prev =>
        (prev ?? []).map(l => {
          const id = l.id ?? l._id ?? l.company_name
          if (id === leadId)
            return updatedLeadDoc ? { ...l, ...updatedLeadDoc, id: leadId } : { ...l, status: newStatus }
          return l
        })
      )
    }
    setRefreshTick(t => t + 1)
  }, [historyLeads])

  const handleLeadUpdate = useCallback((updatedDoc) => {
    if (!updatedDoc) return
    const uid = updatedDoc.id ?? updatedDoc._id
    if (historyLeads !== null) {
      setHistoryLeads(prev =>
        (prev ?? []).map(l => (l.id ?? l._id) === uid ? { ...l, ...updatedDoc } : l)
      )
    }
  }, [historyLeads])

  // ── Bulk Origami enrichment for the currently-shown generated list ────────
  const handleBulkOrigami = useCallback(async () => {
    const targets = activeLeads.filter(l => l.id || l._id)
    if (targets.length === 0) return
    setBulkOrigamiRunning(true)
    setBulkOrigamiResult(null)
    setBulkOrigamiError('')
    try {
      const ids = targets.map(l => l.id ?? l._id).filter(Boolean)
      // Batch max 100 per request; take the first 100 if more
      const batchIds = ids.slice(0, 100)
      const res = await bulkEnrichOrigami(batchIds, selectedCategory, 3)
      setBulkOrigamiResult(res)
      setOrigamiStatsTick(t => t + 1)   // refresh the coverage stats panel
      setRefreshTick(t => t + 1)         // refresh the leads explorer counts
    } catch (err) {
      setBulkOrigamiError(err.message || 'Bulk enrichment failed.')
    } finally {
      setBulkOrigamiRunning(false)
    }
  }, [activeLeads, selectedCategory])

  // ── Sorted generated leads (client-side sort only — no filter) ───────────
  const sortedLeads = useMemo(() => {
    if (!sortDir) return activeLeads
    return [...activeLeads].sort((a, b) => {
      const an = (a.company_name ?? '').toLowerCase()
      const bn = (b.company_name ?? '').toLowerCase()
      return sortDir === 'asc' ? an.localeCompare(bn) : bn.localeCompare(an)
    })
  }, [activeLeads, sortDir])

  const handleGenerate = () => {
    if (!selectedCategory || !selectedState) return
    setHistoryLeads(null)
    setHistoryLabel('')
    setSortDir(null)
    generate({ industry: selectedCategory, state: selectedState, district: selectedDistrict || null, target })
  }

  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    if (activeLeads.length > 0) {
      clear()
      setHistoryLeads(null)
      setHistoryLabel('')
    }
    setSortDir(null)
    setRefreshTick(t => t + 1)
  }

  const handleSortToggle = () =>
    setSortDir((prev) => (prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'))

  const handleLoadFromHistory = (storedLeads, categoryName, runId) => {
    setHistoryLeads(storedLeads)
    setHistoryLabel(runId ? `${categoryName} · ${runId}` : categoryName)
    setSortDir(null)
    setShowHistory(false)
    setRefreshTick(t => t + 1)
  }

  // ── Derived counts (from activeLeads — generated results panel) ──────────
  const totalLeads  = activeLeads.length
  const withEmail   = activeLeads.filter((l) => l.email).length
  const withPhone   = activeLeads.filter((l) => l.company_number || l.phones?.length > 0).length
  const withFounder = activeLeads.filter((l) => l.founder_name).length

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen flex flex-col bg-slate-100">

      {/* ── TOP NAV ───────────────────────────────────────────────────────── */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="h-16 flex items-center justify-between">

            {/* Brand */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center
                              shadow-md shadow-indigo-200">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M13 10V3L4 14h7v7l9-11h-7z"/>
                </svg>
              </div>
              <div>
                <span className="text-base font-bold text-slate-900">LeadCRM</span>
                <span className="hidden sm:inline ml-2 text-xs text-slate-400 font-normal">
                  — Google Maps · CompanyEnrich · Serper · Firecrawl
                </span>
              </div>
            </div>

            {/* Nav actions */}
            <div className="flex items-center gap-2">

              {/* ── Social Leads button ── */}
              <a
                href="/social-leads"
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl
                           border border-indigo-200 bg-indigo-50 text-indigo-700
                           hover:bg-indigo-100 hover:border-indigo-300
                           text-xs font-semibold shadow-sm transition-all duration-150
                           focus:outline-none focus:ring-2 focus:ring-indigo-400"
                title="View social form submission leads"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857
                       M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857
                       m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/>
                </svg>
                <span className="hidden sm:inline">Social Leads</span>
              </a>

              {/* ── Lead Forms button ── */}
              <a
                href="/forms"
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl
                           border border-violet-200 bg-violet-50 text-violet-700
                           hover:bg-violet-100 hover:border-violet-300
                           text-xs font-semibold shadow-sm transition-all duration-150
                           focus:outline-none focus:ring-2 focus:ring-violet-400"
                title="Create & manage lead collection forms"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                </svg>
                <span className="hidden sm:inline">Lead Forms</span>
              </a>

              {/* ── Origami Enrichment button ── */}
              <a
                href="/origami"
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl
                           border border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700
                           hover:bg-fuchsia-100 hover:border-fuchsia-300
                           text-xs font-semibold shadow-sm transition-all duration-150
                           focus:outline-none focus:ring-2 focus:ring-fuchsia-400"
                title="Origami people enrichment — find founders & decision-makers"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3
                       m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547
                       A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531
                       c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                </svg>
                <span className="hidden sm:inline">Origami</span>
              </a>

              {/* ── History button ── */}
              <button
                onClick={() => setShowHistory(true)}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl
                           border border-slate-200 bg-white text-slate-600
                           hover:bg-indigo-50 hover:border-indigo-300 hover:text-indigo-700
                           text-xs font-semibold shadow-sm transition-all duration-150
                           focus:outline-none focus:ring-2 focus:ring-indigo-400"
                title="View all past leads from MongoDB"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span className="hidden sm:inline">History</span>
              </button>

              {/* ── Follow-ups button ── */}
              <button
                onClick={() => setShowFollowUps(true)}
                className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl
                           border border-rose-200 bg-rose-50 text-rose-700
                           hover:bg-rose-100 hover:border-rose-300
                           text-xs font-semibold shadow-sm transition-all duration-150
                           focus:outline-none focus:ring-2 focus:ring-rose-400"
                title="View scheduled follow-ups"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                </svg>
                <span className="hidden sm:inline">Follow-ups</span>
              </button>

              <RefreshLeadsButton
                isRefreshing={isRefreshing}
                isLoading={isLoading}
                onClick={refreshFromDB}
              />
            </div>
          </div>
        </div>
      </header>

      {/* ── MAIN CONTENT ──────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 lg:px-8 py-8">

        {/* Category picker */}
        <CategoryScroller
          selectedCategory={selectedCategory}
          onSelectCategory={handleCategorySelect}
        />

        {/* Location + target */}
        <GeoSelector
          selectedState={selectedState}
          selectedDistrict={selectedDistrict}
          target={target}
          onStateChange={setSelectedState}
          onDistrictChange={setSelectedDistrict}
          onTargetChange={setTarget}
        />

        {/* Generate button */}
        <GenerateLeadsButton
          ready={Boolean(selectedCategory && selectedState)}
          isLoading={isLoading}
          onClick={handleGenerate}
          selectedCategory={selectedCategory}
        />

        {/* Error banner */}
        {error && <ErrorBanner message={error} onDismiss={() => { clear(); setHistoryLeads(null) }} />}

        {/* History-source banner */}
        {historyLeads !== null && (
          <div className="mb-5 flex items-center justify-between gap-3 px-4 py-3
                          rounded-xl bg-amber-50 border border-amber-200">
            <div className="flex items-center gap-2 text-xs text-amber-700">
              <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <span>
                Showing <strong>{historyLeads.length}</strong> past leads
                from <strong>{historyLabel}</strong> (loaded from MongoDB history)
              </span>
            </div>
            <button
              onClick={() => { setHistoryLeads(null); setHistoryLabel('') }}
              className="text-xs text-amber-600 hover:text-amber-800 font-semibold
                         underline underline-offset-2 flex-shrink-0"
            >
              Clear
            </button>
          </div>
        )}

        {/* Stat cards */}
        {totalLeads > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
            <StatCard
              label="Companies found" value={totalLeads} color="bg-indigo-50"
              icon={<svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
              </svg>}
            />
            <StatCard
              label="With email" value={withEmail} color="bg-emerald-50"
              icon={<svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
              </svg>}
            />
            <StatCard
              label="With phone" value={withPhone} color="bg-sky-50"
              icon={<svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>
              </svg>}
            />
            <StatCard
              label="With founder" value={withFounder} color="bg-amber-50"
              icon={<svg className="w-5 h-5 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
              </svg>}
            />
          </div>
        )}

        {/* Pipeline stats bar (only for fresh generate, not history) */}
        {historyLeads === null && totalLeads > 0 && pipelineStats && (
          <PipelineStatsBar stats={pipelineStats} />
        )}

        {/* ── Generated Results card (fresh pipeline or history) ──────── */}
        {totalLeads > 0 && (
          <div className="crm-card p-5 sm:p-6">

            {/* Header row */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
              <div>
                <h2 className="text-base font-bold text-slate-800">
                  {historyLeads !== null ? `History — ${historyLabel}` : 'Generated Leads'}
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {isLoading
                    ? 'Discovering and enriching companies…'
                    : `${totalLeads} compan${totalLeads !== 1 ? 'ies' : 'y'}`
                      + (historyLeads !== null
                          ? ' · from MongoDB history'
                          : selectedState
                            ? ` · ${selectedDistrict ? selectedDistrict + ', ' : ''}${selectedState}`
                            : '')
                  }
                </p>
              </div>
              <div className="flex items-center gap-2">
                {/* Bulk Origami Enrichment button — runs on all leads in this panel */}
                {totalLeads > 0 && !isLoading && (
                  <button
                    onClick={handleBulkOrigami}
                    disabled={bulkOrigamiRunning}
                    title={`Run Origami enrichment on all ${Math.min(totalLeads, 100)} leads to find founders and decision-makers`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                               bg-violet-600 text-white hover:bg-violet-700 disabled:opacity-60
                               transition-colors focus:outline-none focus:ring-2 focus:ring-violet-400"
                  >
                    {bulkOrigamiRunning
                      ? <>
                          <svg className="w-3.5 h-3.5 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                          </svg>
                          Enriching…
                        </>
                      : <>
                          <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                              d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
                          </svg>
                          Bulk Enrich
                        </>
                    }
                  </button>
                )}
                {totalLeads > 0 && (
                  <button
                    onClick={handleSortToggle}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                               bg-slate-100 hover:bg-slate-200 text-slate-600 text-xs font-medium
                               transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12"/>
                    </svg>
                    {sortDir === 'asc' ? 'A → Z' : sortDir === 'desc' ? 'Z → A' : 'Sort'}
                  </button>
                )}
              </div>
            </div>

            {/* Bulk Origami result banner */}
            {bulkOrigamiError && (
              <div className="mb-4 flex items-center gap-2 px-4 py-2.5 rounded-xl
                              bg-rose-50 border border-rose-200 text-xs text-rose-700">
                <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
                </svg>
                Bulk enrichment error: {bulkOrigamiError}
                <button onClick={() => setBulkOrigamiError('')} className="ml-auto text-rose-500 hover:text-rose-700">✕</button>
              </div>
            )}
            {bulkOrigamiResult && !bulkOrigamiError && (
              <div className="mb-4 flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 py-2.5 rounded-xl
                              bg-violet-50 border border-violet-200 text-xs text-violet-700">
                <span className="flex items-center gap-1.5 font-semibold">
                  <span className="w-1.5 h-1.5 rounded-full bg-violet-500 flex-shrink-0"/>
                  Origami enrichment complete
                </span>
                <span>✅ Succeeded: <strong>{bulkOrigamiResult.succeeded ?? 0}</strong></span>
                {(bulkOrigamiResult.failed ?? 0) > 0 && (
                  <span>❌ Failed: <strong>{bulkOrigamiResult.failed}</strong></span>
                )}
                <span>🔍 Founders found: <strong>{bulkOrigamiResult.founders_found ?? 0}</strong></span>
                <span>⚡ Origami enriched: <strong>{bulkOrigamiResult.origami_enriched ?? 0}</strong></span>
                {bulkOrigamiResult.elapsed_seconds != null && (
                  <span>⏱ <strong>{bulkOrigamiResult.elapsed_seconds}s</strong></span>
                )}
                <button
                  onClick={() => setBulkOrigamiResult(null)}
                  className="ml-auto text-violet-500 hover:text-violet-700"
                >✕</button>
              </div>
            )}

            <LeadsTable
              leads={sortedLeads}
              isLoading={isLoading}
              sortDir={sortDir}
              onSortChange={handleSortToggle}
              onStatusUpdate={handleStatusUpdate}
              onLeadUpdate={handleLeadUpdate}
            />
          </div>
        )}

        {/* ── All Leads Explorer (server-driven: tabs + search + date) ── */}
        <LeadsExplorer
          category={selectedCategory}
          refreshTrigger={refreshTick}
          onStatusUpdate={handleStatusUpdate}
          onLeadUpdate={handleLeadUpdate}
        />

        {/* ── Origami Coverage Stats (live from DB — never hardcoded) ── */}
        <div className="mt-6">
          <OrigamiStatsPanel
            category={selectedCategory}
            refreshTrigger={origamiStatsTick}
          />
        </div>
      </main>

      {/* ── HISTORY PANEL (slide-in drawer) ───────────────────────────────── */}
      {showHistory && (
        <HistoryPanel
          onClose={() => setShowHistory(false)}
          onLoadLeads={handleLoadFromHistory}
        />
      )}

      {/* ── FOLLOW-UPS PANEL (modal) ───────────────────────────────────────── */}
      {showFollowUps && (
        <FollowUpsPanel
          category={selectedCategory}
          onClose={() => setShowFollowUps(false)}
        />
      )}
    </div>
  )
}
