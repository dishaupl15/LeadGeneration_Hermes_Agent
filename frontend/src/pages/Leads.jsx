/**
 * Leads.jsx  —  /
 * ───────────────
 * Main leads workspace — browse, filter, search, and manage all stored leads.
 *
 * Features (all existing, preserved):
 *   - Status tabs: New · Interested · Not Interested · Follow-ups · All
 *   - Search (debounced, 300ms)
 *   - Date range filter
 *   - Category filter (all-categories when none selected)
 *   - CSV + Excel export (existing endpoints)
 *   - Pagination
 *   - Status change (Interested / Not Interested)
 *   - Notes + Follow-up via LeadDetailPanel / FollowUpModal
 *   - PDL contacts drawer
 *   - Category breakdown strip in all-categories mode
 *
 * The History-panel "Load into table" flow is preserved via historyLeads state.
 */

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import Layout from '../components/Layout'
import LeadsTable from '../components/LeadsTable'
import HistoryPanel from '../components/HistoryPanel'
import FollowUpsPanel from '../components/FollowUpsPanel'
import {
  getLeads, getLeadStatusCounts, buildExportUrl, buildAllCategoriesExcelUrl,
} from '../services/api'
import { CATEGORIES } from '../config/categories'

const PER_PAGE = 50

/* ── Tab definitions ──────────────────────────────────────────────────────── */
const TABS = [
  { key: 'new_leads',      label: 'New',           countKey: 'new',           dot: 'bg-sky-400',     active: 'bg-sky-600 text-white border-sky-600',     inactive: 'bg-white text-sky-700 border-sky-200 hover:bg-sky-50' },
  { key: 'old_untouched',  label: 'Untouched',     countKey: 'old_untouched', dot: 'bg-orange-400',  active: 'bg-orange-500 text-white border-orange-500',inactive: 'bg-white text-orange-700 border-orange-200 hover:bg-orange-50' },
  { key: 'interested',     label: 'Interested',    countKey: 'interested',    dot: 'bg-emerald-400', active: 'bg-emerald-600 text-white border-emerald-600',inactive:'bg-white text-emerald-700 border-emerald-200 hover:bg-emerald-50' },
  { key: 'not_interested', label: 'Not Interested',countKey: 'not_interested',dot: 'bg-rose-400',    active: 'bg-rose-600 text-white border-rose-600',    inactive: 'bg-white text-rose-700 border-rose-200 hover:bg-rose-50' },
  { key: 'follow_ups',     label: 'Follow-ups',    countKey: 'follow_ups',    dot: 'bg-indigo-400',  active: 'bg-indigo-600 text-white border-indigo-600', inactive: 'bg-white text-indigo-700 border-indigo-200 hover:bg-indigo-50' },
  { key: 'all',            label: 'All Leads',     countKey: 'total',         dot: 'bg-slate-400',   active: 'bg-slate-800 text-white border-slate-800',  inactive: 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50' },
]

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE
   ══════════════════════════════════════════════════════════════════════════════ */
export default function Leads() {
  const navigate    = useNavigate()
  const routeState  = useLocation().state

  /* ── UI state ─────────────────────────────────────────────────────────── */
  const [activeTab,   setActiveTab]   = useState('all')
  const [search,      setSearch]      = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  // If navigated from Dashboard "Today's Leads", pre-fill today's date range
  const todayIso = new Date().toISOString().slice(0, 10)
  const [dateFrom,    setDateFrom]    = useState(routeState?.todayFilter ? todayIso : '')
  const [dateTo,      setDateTo]      = useState(routeState?.todayFilter ? todayIso : '')
  const [category,    setCategory]    = useState('')  // '' = all categories
  const [page,        setPage]        = useState(1)
  const [refreshTick, setRefreshTick] = useState(0)

  /* ── panel state ──────────────────────────────────────────────────────── */
  const [showHistory,   setShowHistory]   = useState(false)
  const [showFollowUps, setShowFollowUps] = useState(false)

  /* ── history-load override (from HistoryPanel "Load into table" or History page nav) */
  const [historyLeads, setHistoryLeads] = useState(
    routeState?.historyLeads ?? null
  )
  const [historyLabel, setHistoryLabel] = useState(
    routeState?.historyLabel ?? ''
  )

  /* ── data state ───────────────────────────────────────────────────────── */
  const [leads,      setLeads]      = useState([])
  const [total,      setTotal]      = useState(0)
  const [byCategory, setByCategory] = useState([])
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState('')
  const [counts,        setCounts]        = useState({})
  const [countsLoading, setCountsLoading] = useState(false)

  const isAllCategories = !category

  /* ── debounce search ──────────────────────────────────────────────────── */
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  /* ── reset to page 1 on filter change ────────────────────────────────── */
  useEffect(() => { setPage(1) }, [category, activeTab, debouncedSearch, dateFrom, dateTo])

  /* ── fetch counts ─────────────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false
    setCountsLoading(true)
    getLeadStatusCounts(category || null, isAllCategories)
      .then(res => { if (!cancelled) setCounts(res.counts ?? {}) })
      .catch(() => { if (!cancelled) setCounts({}) })
      .finally(() => { if (!cancelled) setCountsLoading(false) })
    return () => { cancelled = true }
  }, [category, isAllCategories, refreshTick])

  /* ── fetch leads ──────────────────────────────────────────────────────── */
  useEffect(() => {
    // If history override is active, show those leads directly
    if (historyLeads !== null) return
    let cancelled = false
    setLoading(true)
    setError('')
    const params = {
      ...(category ? { category } : {}),
      ...(isAllCategories && !category ? { all_categories: true } : {}),
      tab: activeTab,
      page,
      per_page: PER_PAGE,
      ...(debouncedSearch ? { search: debouncedSearch } : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo   ? { date_to:   dateTo }   : {}),
    }
    getLeads(params)
      .then(res => {
        if (!cancelled) {
          setLeads(res.leads ?? [])
          setTotal(res.total ?? 0)
          setByCategory(res.by_category ?? [])
        }
      })
      .catch(err => { if (!cancelled) setError(err.message || 'Failed to load leads.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [category, isAllCategories, activeTab, page, debouncedSearch, dateFrom, dateTo, refreshTick, historyLeads])

  const totalPages   = Math.max(1, Math.ceil(total / PER_PAGE))
  const displayLeads = historyLeads !== null ? historyLeads : leads
  const displayTotal = historyLeads !== null ? historyLeads.length : total

  /* ── handlers ─────────────────────────────────────────────────────────── */
  const handleStatusUpdate = useCallback((leadId, newStatus, updatedDoc) => {
    if (historyLeads !== null) {
      setHistoryLeads(prev => (prev ?? []).map(l => {
        const id = l.id ?? l._id ?? l.company_name
        return id === leadId
          ? (updatedDoc ? { ...l, ...updatedDoc, id: leadId } : { ...l, status: newStatus })
          : l
      }))
    }
    setRefreshTick(t => t + 1)
  }, [historyLeads])

  const handleLeadUpdate = useCallback((updatedDoc) => {
    if (!updatedDoc) return
    const uid = updatedDoc.id ?? updatedDoc._id
    if (historyLeads !== null) {
      setHistoryLeads(prev => (prev ?? []).map(l => (l.id ?? l._id) === uid ? { ...l, ...updatedDoc } : l))
    } else {
      setLeads(prev => prev.map(l => (l.id ?? l._id) === uid ? { ...l, ...updatedDoc } : l))
    }
  }, [historyLeads])

  const handleLoadFromHistory = (storedLeads, categoryName, runId) => {
    setHistoryLeads(storedLeads)
    setHistoryLabel(runId ? `${categoryName} · ${runId}` : categoryName)
    setShowHistory(false)
    setRefreshTick(t => t + 1)
  }

  const clearHistoryOverride = () => {
    setHistoryLeads(null)
    setHistoryLabel('')
    setRefreshTick(t => t + 1)
  }

  /* ── export params ────────────────────────────────────────────────────── */
  const exportParams = useMemo(() => ({
    ...(category ? { category } : {}),
    ...(activeTab !== 'all' ? { tab: activeTab } : {}),
    ...(debouncedSearch ? { search: debouncedSearch } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo   ? { date_to:   dateTo }   : {}),
  }), [category, activeTab, debouncedSearch, dateFrom, dateTo])

  return (
    <Layout
      followUpRefreshTick={refreshTick}
      onOpenFollowUps={() => setShowFollowUps(true)}
      onNavigateToLead={(lead) => {
        setHistoryLeads(null)
        setHistoryLabel('')
        setRefreshTick(t => t + 1)
      }}
    >
      <div className="max-w-[1400px] mx-auto px-4 sm:px-6 lg:px-8 py-6">

        {/* ── Header row ────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
          <div>
            <h1 className="text-xl font-bold text-slate-900">
              All Leads
              {!countsLoading && (
                <span className="text-base font-normal text-slate-400 ml-2">— {counts.total ?? 0} total</span>
              )}
            </h1>
            {historyLabel && (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200
                                 px-2 py-0.5 rounded-full font-medium">{historyLabel}</span>
                <button onClick={clearHistoryOverride}
                  className="text-xs text-slate-400 hover:text-slate-600 transition-colors">
                  ✕ Clear
                </button>
              </div>
            )}
            {!historyLabel && routeState?.todayFilter && dateFrom === dateTo && dateFrom && (
              <div className="flex items-center gap-2 mt-1">
                <span className="text-xs text-indigo-700 bg-indigo-50 border border-indigo-200
                                 px-2 py-0.5 rounded-full font-medium">
                  Showing today's leads
                </span>
                <button onClick={() => { setDateFrom(''); setDateTo('') }}
                  className="text-xs text-slate-400 hover:text-slate-600 transition-colors">
                  ✕ Clear
                </button>
              </div>
            )}
          </div>

          {/* Right: export + history */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setShowHistory(true)}
              className="btn-secondary px-3 py-2 text-xs gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              History
            </button>
            <a href={buildExportUrl('csv', exportParams)} download
              className="btn-secondary px-3 py-2 text-xs gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
              </svg>
              CSV
            </a>
            <a href={buildExportUrl('excel', exportParams)} download
              className="btn-secondary px-3 py-2 text-xs gap-1.5">
              Excel
            </a>
            {isAllCategories && (
              <a href={buildAllCategoriesExcelUrl()} download
                className="btn-secondary px-3 py-2 text-xs gap-1.5">
                All (xlsx)
              </a>
            )}
          </div>
        </div>

        {/* ── Filters ──────────────────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-slate-200 p-4 mb-4 space-y-3">

          {/* Search + date */}
          <div className="flex flex-wrap gap-3">
            {/* Search */}
            <div className="relative flex-1 min-w-[200px]">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
              </div>
              <input type="text" value={search} onChange={e => setSearch(e.target.value)}
                placeholder="Search company, email, phone…"
                className="crm-input pl-9 pr-8 text-sm w-full" />
              {search && (
                <button onClick={() => setSearch('')}
                  className="absolute inset-y-0 right-0 flex items-center pr-2.5
                             text-slate-400 hover:text-slate-600">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              )}
            </div>

            {/* Date from */}
            <div className="flex flex-col gap-0.5">
              <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">From</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
                     className="crm-input text-sm w-36" />
            </div>

            {/* Date to */}
            <div className="flex flex-col gap-0.5">
              <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">To</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
                     className="crm-input text-sm w-36" />
            </div>

            {/* Category */}
            <div className="flex flex-col gap-0.5">
              <label className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">Category</label>
              <div className="relative">
                <select value={category} onChange={e => setCategory(e.target.value)}
                        className="crm-input pr-9 appearance-none text-sm w-44">
                  <option value="">All Categories</option>
                  {CATEGORIES.map(c => <option key={c.label} value={c.label}>{c.label}</option>)}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                  </svg>
                </div>
              </div>
            </div>

            {/* Clear filters */}
            {(search || dateFrom || dateTo || category) && (
              <button
                onClick={() => { setSearch(''); setDateFrom(''); setDateTo(''); setCategory('') }}
                className="self-end mb-0.5 inline-flex items-center gap-1 px-3 py-2 rounded-lg
                           text-xs font-semibold text-slate-500 bg-slate-100 hover:bg-slate-200 transition-colors">
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                </svg>
                Clear
              </button>
            )}
          </div>

          {/* Tab bar */}
          <div className="flex flex-wrap gap-1.5">
            {TABS.map(tab => (
              <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold
                            border transition-all duration-150 focus:outline-none
                            ${activeTab === tab.key ? tab.active : tab.inactive}`}>
                <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${activeTab === tab.key ? 'bg-white/80' : tab.dot}`}/>
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
        </div>

        {/* ── Category breakdown strip (all-categories mode) ──────────── */}
        {isAllCategories && byCategory.length > 0 && !loading && historyLeads === null && (
          <div className="mb-4 p-3 rounded-xl bg-slate-50 border border-slate-200">
            <p className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
              Category breakdown
            </p>
            <div className="flex flex-wrap gap-1.5">
              {byCategory.map(bc => (
                <button key={bc.category}
                  onClick={() => setCategory(bc.category)}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                             bg-white border border-slate-200 text-slate-700 text-[11px]
                             font-medium shadow-sm hover:border-indigo-300 hover:bg-indigo-50 transition-colors">
                  <span className="font-bold text-slate-900">{bc.category}</span>
                  <span className="inline-flex items-center justify-center min-w-[20px] h-4 px-1.5
                                   rounded-full bg-indigo-100 text-indigo-700 text-[10px] font-bold">
                    {bc.count}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* ── Error ───────────────────────────────────────────────────── */}
        {error && <p className="text-sm text-rose-600 mb-3">{error}</p>}

        {/* ── Table ───────────────────────────────────────────────────── */}
        <LeadsTable
          leads={displayLeads}
          isLoading={loading && historyLeads === null}
          searchQuery={debouncedSearch}
          onStatusUpdate={handleStatusUpdate}
          onLeadUpdate={handleLeadUpdate}
        />

        {/* ── Pagination ─────────────────────────────────────────────── */}
        {totalPages > 1 && historyLeads === null && (
          <div className="flex items-center justify-between mt-4 pt-3 border-t border-slate-200">
            <span className="text-xs text-slate-500">
              Page <strong>{page}</strong> of <strong>{totalPages}</strong>
              {' · '}<strong>{displayTotal}</strong> leads
            </span>
            <div className="flex gap-1.5">
              <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page === 1}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-200
                           bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                ← Prev
              </button>
              <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page === totalPages}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-200
                           bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed">
                Next →
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── History panel ────────────────────────────────────────────── */}
      {showHistory && (
        <HistoryPanel
          onClose={() => setShowHistory(false)}
          onLoadLeads={handleLoadFromHistory}
        />
      )}

      {/* ── Follow-ups panel ──────────────────────────────────────────── */}
      {showFollowUps && (
        <FollowUpsPanel
          category={category || null}
          onClose={() => setShowFollowUps(false)}
        />
      )}
    </Layout>
  )
}
