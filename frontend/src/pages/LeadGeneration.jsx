import { useState, useMemo, useEffect } from 'react'
import CategoryScroller from '../components/CategoryScroller'
import RefreshLeadsButton from '../components/RefreshLeadsButton'
import LeadsTable from '../components/LeadsTable'
import ErrorBanner from '../components/ErrorBanner'
import HistoryPanel from '../components/HistoryPanel'
import { useGenerateLeads } from '../hooks/useGenerateLeads'
import { getMapsStates, getMapsDistricts } from '../services/api'

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

/* ══════════════════════════════════════════════════════════════════════════
   MAIN PAGE
   ══════════════════════════════════════════════════════════════════════════ */
export default function LeadGeneration() {
  // ── UI state ──────────────────────────────────────────────────────────────
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedState,    setSelectedState]    = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  const [target,           setTarget]           = useState(10)
  const [searchQuery,      setSearchQuery]      = useState('')
  const [sortDir,          setSortDir]          = useState(null)
  const [showHistory,      setShowHistory]      = useState(false)

  // History-override: when user clicks "Load into table" in the history panel,
  // we store those leads here so they're displayed WITHOUT triggering a new API call.
  const [historyLeads, setHistoryLeads] = useState(null)   // null = not active
  const [historyLabel, setHistoryLabel] = useState('')

  // ── Lead generation hook ─────────────────────────────────────────────────
  const {
    leads, isLoading, isRefreshing, error, pipelineStats,
    generate, refreshFromDB, clear,
  } = useGenerateLeads()

  // Which leads to actually render — history override wins until a fresh
  // generate or clear resets it.
  const activeLeads = historyLeads !== null ? historyLeads : leads

  // ── Filtered + sorted active leads ───────────────────────────────────────
  const filteredLeads = useMemo(() => {
    let result = activeLeads
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter((l) => (l.company_name ?? '').toLowerCase().includes(q))
    }
    if (sortDir) {
      result = [...result].sort((a, b) => {
        const an = (a.company_name ?? '').toLowerCase()
        const bn = (b.company_name ?? '').toLowerCase()
        return sortDir === 'asc' ? an.localeCompare(bn) : bn.localeCompare(an)
      })
    }
    return result
  }, [activeLeads, searchQuery, sortDir])

  // ── Handlers ─────────────────────────────────────────────────────────────
  const handleGenerate = () => {
    if (!selectedCategory || !selectedState) return
    // Clear any history override so fresh results are shown
    setHistoryLeads(null)
    setHistoryLabel('')
    setSearchQuery('')
    setSortDir(null)
    generate({ industry: selectedCategory, state: selectedState, district: selectedDistrict || null, target })
  }

  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    // Clear table if it had previous results
    if (activeLeads.length > 0) {
      clear()
      setHistoryLeads(null)
      setHistoryLabel('')
    }
    setSearchQuery('')
    setSortDir(null)
  }

  const handleSortToggle = () =>
    setSortDir((prev) => (prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'))

  // Called from HistoryPanel — load stored leads into the main table
  const handleLoadFromHistory = (storedLeads, categoryName, runId) => {
    setHistoryLeads(storedLeads)
    setHistoryLabel(runId ? `${categoryName} · ${runId}` : categoryName)
    setSearchQuery('')
    setSortDir(null)
    setShowHistory(false)
  }

  // ── Derived counts (always from activeLeads) ─────────────────────────────
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

              {/* Refresh from DB */}
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

        {/* History-source banner — shown when table is loaded from history */}
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

        {/* Results card */}
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
                  : totalLeads === 0
                    ? 'No results yet — select a category and state, then click Generate Leads.'
                    : `${filteredLeads.length} of ${totalLeads} compan${totalLeads !== 1 ? 'ies' : 'y'}`
                      + (historyLeads !== null
                          ? ' · from MongoDB history'
                          : selectedState
                            ? ` · ${selectedDistrict ? selectedDistrict + ', ' : ''}${selectedState}`
                            : '')
                }
              </p>
            </div>

            <div className="flex items-center gap-2">
              {/* Sort toggle */}
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

          {/* Search */}
          {totalLeads > 0 && (
            <div className="relative mb-4">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5">
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by company name…"
                className="crm-input pl-10 pr-10"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute inset-y-0 right-0 flex items-center pr-3
                             text-slate-400 hover:text-slate-600 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M6 18L18 6M6 6l12 12"/>
                  </svg>
                </button>
              )}
            </div>
          )}

          {/* Table */}
          <LeadsTable
            leads={filteredLeads}
            isLoading={isLoading}
            searchQuery={searchQuery}
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
    </div>
  )
}
