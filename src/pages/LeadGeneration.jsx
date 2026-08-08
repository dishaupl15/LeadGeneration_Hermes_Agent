import { useState, useMemo } from 'react'
import CategoryScroller from '../components/CategoryScroller'
import GenerateButton from '../components/GenerateButton'
import RefreshLeadsButton from '../components/RefreshLeadsButton'
import SearchBar from '../components/SearchBar'
import LeadsTable from '../components/LeadsTable'
import ErrorBanner from '../components/ErrorBanner'
import { useGenerateLeads } from '../hooks/useGenerateLeads'
import { CATEGORY_LABELS } from '../config/categories'

/* ── Constants ──────────────────────────────────────────────────── */
const DEFAULT_CITY  = 'Pune'
const DEFAULT_COUNT = 10

/* ── Stat card ──────────────────────────────────────────────────── */
function StatCard({ label, value, icon, color }) {
  return (
    <div className="crm-card p-5 flex items-center gap-4">
      <div className={`w-11 h-11 rounded-xl flex items-center justify-center ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-slate-800">{value}</p>
        <p className="text-xs text-slate-500 mt-0.5">{label}</p>
      </div>
    </div>
  )
}

/* ── Page ───────────────────────────────────────────────────────── */
export default function LeadGeneration() {
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedCity]                          = useState(DEFAULT_CITY)
  const [selectedCount]                         = useState(DEFAULT_COUNT)
  const [searchQuery, setSearchQuery]           = useState('')
  const [sortDir, setSortDir]                   = useState(null) // null | 'asc' | 'desc'

  // ── API state via custom hook ──────────────────────────────────
  const { leads, isLoading, isRefreshing, error, generate, refresh, refreshFromDB, clear } = useGenerateLeads()

  // ── Client-side: search by company name + sort by company name ─
  const filteredLeads = useMemo(() => {
    let result = leads

    // 1. Search by company name
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter((l) =>
        (l.company_name ?? '').toLowerCase().includes(q)
      )
    }

    // 2. Sort by company name
    if (sortDir) {
      result = [...result].sort((a, b) => {
        const nameA = (a.company_name ?? '').toLowerCase()
        const nameB = (b.company_name ?? '').toLowerCase()
        return sortDir === 'asc'
          ? nameA.localeCompare(nameB)
          : nameB.localeCompare(nameA)
      })
    }

    return result
  }, [leads, searchQuery, sortDir])

  const handleSortToggle = () => {
    setSortDir((prev) => (prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'))
  }

  const handleGenerate = () => {
    if (!selectedCategory) return
    setSearchQuery('')
    setSortDir(null)
    generate({
      industry: selectedCategory,
      city:     selectedCity,
      count:    selectedCount,
    })
  }

  const handleRefresh = () => {
    setSearchQuery('')
    setSortDir(null)
    refresh()
  }

  const handleRefreshFromDB = () => {
    setSearchQuery('')
    setSortDir(null)
    refreshFromDB()
  }

  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    if (leads.length > 0) clear()
    setSearchQuery('')
    setSortDir(null)
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-100">

      {/* ══════════════ TOP NAV ══════════════ */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="h-16 flex items-center justify-between">

            {/* Brand */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center shadow-md shadow-indigo-200">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <div>
                <span className="text-base font-bold text-slate-900">LeadCRM</span>
                <span className="hidden sm:inline ml-2 text-xs text-slate-400 font-normal">
                  — Powered by Hermes AI
                </span>
              </div>
            </div>

            {/* Nav links */}
            <nav className="hidden md:flex items-center gap-1">
              {['Dashboard', 'Lead Generation', 'Contacts', 'Reports', 'Settings'].map((item) => (
                <a
                  key={item}
                  href="#"
                  onClick={(e) => e.preventDefault()}
                  className={`
                    px-3.5 py-2 rounded-lg text-sm font-medium transition-colors
                    ${item === 'Lead Generation'
                      ? 'bg-indigo-50 text-indigo-700'
                      : 'text-slate-500 hover:text-slate-800 hover:bg-slate-100'
                    }
                  `}
                >
                  {item}
                </a>
              ))}
            </nav>

            {/* Right actions */}
            <div className="flex items-center gap-3">
              <button
                aria-label="Notifications"
                className="relative w-9 h-9 rounded-full flex items-center justify-center text-slate-500 hover:bg-slate-100 transition-colors"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-rose-500 rounded-full ring-2 ring-white" />
              </button>
              <div className="w-9 h-9 rounded-full bg-indigo-600 flex items-center justify-center text-white text-sm font-bold cursor-pointer shadow-sm">
                A
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ══════════════ MAIN CONTENT ══════════════ */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* Page heading */}
        <div className="mb-7 fade-in-up">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
                Lead Generation
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Select an industry, generate targeted B2B leads, and export to your CRM pipeline.
              </p>
            </div>

            {/* API status indicator + Refresh Leads */}
            <div className="flex items-center gap-3 self-start">
              <RefreshLeadsButton
                isRefreshing={isRefreshing}
                isLoading={isLoading}
                onClick={handleRefreshFromDB}
              />
              <div className={`
                inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium
                ${error
                  ? 'bg-rose-50 border border-rose-200 text-rose-700'
                  : isLoading || isRefreshing
                    ? 'bg-amber-50 border border-amber-200 text-amber-700'
                    : 'bg-emerald-50 border border-emerald-200 text-emerald-700'
                }
              `}>
                <span className={`w-2 h-2 rounded-full ${
                  error ? 'bg-rose-500' : isLoading || isRefreshing ? 'bg-amber-400 animate-pulse' : 'bg-emerald-500 animate-pulse'
                }`} />
                {error ? 'Connection Error' : isLoading ? 'Fetching…' : isRefreshing ? 'Refreshing…' : 'API Ready'}
              </div>
            </div>
          </div>
        </div>

        {/* ── Stats row ── */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-7">
          <StatCard
            label="Total Leads"
            value={leads.length}
            color="bg-indigo-100 text-indigo-600"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            }
          />
          <StatCard
            label="Categories"
            value={CATEGORY_LABELS.length}
            color="bg-sky-100 text-sky-600"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
              </svg>
            }
          />
          <StatCard
            label="Active Category"
            value={selectedCategory ? '1' : '0'}
            color="bg-violet-100 text-violet-600"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
              </svg>
            }
          />
          <StatCard
            label="Visible Results"
            value={filteredLeads.length}
            color="bg-amber-100 text-amber-600"
            icon={
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
            }
          />
        </div>

        {/* ── Category scroller ── */}
        <CategoryScroller
          selectedCategory={selectedCategory}
          onSelectCategory={handleCategorySelect}
        />

        {/* ── Generate button ── */}
        <GenerateButton
          selectedCategory={selectedCategory}
          isLoading={isLoading}
          onClick={handleGenerate}
        />

        {/* ── Error banner ── */}
        {error && (
          <ErrorBanner
            message={error}
            onRetry={handleGenerate}
            onDismiss={() => clear()}
          />
        )}

        {/* ── Table section ── */}
        <div className="crm-card p-5 sm:p-6">
          {/* Table header row */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
            <div>
              <h2 className="text-base font-bold text-slate-800">Generated Leads</h2>
              <p className="text-xs text-slate-400 mt-0.5">
                {isLoading
                  ? 'Fetching leads from the backend…'
                  : leads.length === 0
                    ? 'No leads yet — select a category and click Generate.'
                    : `${filteredLeads.length} of ${leads.length} lead${leads.length !== 1 ? 's' : ''} · ${selectedCity}`
                }
              </p>
            </div>

            {selectedCategory && (
              <span className="
                inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                bg-indigo-100 text-indigo-700 text-xs font-semibold border border-indigo-200
                self-start sm:self-auto
              ">
                <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd"
                    d="M3 3a1 1 0 011-1h12a1 1 0 011 1v3a1 1 0 01-.293.707L12 11.414V15a1 1 0 01-.293.707l-2 2A1 1 0 018 17v-5.586L3.293 6.707A1 1 0 013 6V3z"
                    clipRule="evenodd" />
                </svg>
                {selectedCategory}
              </span>
            )}
          </div>

          {/* Search + Refresh */}
          <SearchBar
            value={searchQuery}
            onChange={setSearchQuery}
            onRefresh={handleRefresh}
            isLoading={isLoading}
            totalResults={filteredLeads.length}
          />

          {/* Leads table */}
          <LeadsTable
            leads={filteredLeads}
            isLoading={isLoading}
            error={error}
            searchQuery={searchQuery}
            sortDir={sortDir}
            onSortChange={handleSortToggle}
          />
        </div>

      </main>

      {/* ══════════════ FOOTER ══════════════ */}
      <footer className="border-t border-slate-200 bg-white mt-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded bg-indigo-600 flex items-center justify-center">
              <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span>© 2026 LeadCRM · All rights reserved</span>
          </div>
          <div className="flex items-center gap-4">
            <span className="flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              Phase 2 — Live API
            </span>
            <span>v2.0.0</span>
          </div>
        </div>
      </footer>

    </div>
  )
}
