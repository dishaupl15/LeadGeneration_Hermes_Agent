/**
 * GenerateLeads.jsx
 * ─────────────────
 * Dedicated page for the lead-generation workflow.
 *
 * Layout:
 *   Step 1 — Select Industry (category pills)
 *   Step 2 — Choose Location (state + district)
 *   Step 3 — Number of Leads
 *   Step 4 — Generate button
 *   Step 5 — Results appear below (table of new leads from this run)
 *
 * Uses the existing useGenerateLeads hook and generateRedditLeads API.
 * All backend provider names (Google Maps, Serper, Firecrawl, etc.)
 * are hidden from the user — they see only "Generate Leads".
 */

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import { CATEGORIES } from '../config/categories'
import { useGenerateLeads } from '../hooks/useGenerateLeads'
import LeadsTable from '../components/LeadsTable'
import ErrorBanner from '../components/ErrorBanner'
import {
  getMapsStates, getMapsDistricts, generateRedditLeads,
} from '../services/api'

/* ── Step heading ─────────────────────────────────────────────────────────── */
function StepLabel({ number, label, done }) {
  return (
    <div className="flex items-center gap-2.5 mb-3">
      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0
                       ${done ? 'bg-indigo-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
        {done ? (
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
          </svg>
        ) : number}
      </div>
      <span className="text-sm font-semibold text-slate-700">{label}</span>
    </div>
  )
}

/* ── Industry selector — searchable dropdown + quick pills for top picks ─── */
function IndustrySelector({ selectedCategory, onSelect }) {
  const [open,   setOpen]   = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const filtered = search.trim()
    ? CATEGORIES.filter(c => c.label.toLowerCase().includes(search.toLowerCase()))
    : CATEGORIES

  const handleSelect = (label) => {
    onSelect(label)
    setOpen(false)
    setSearch('')
  }

  const selected = CATEGORIES.find(c => c.label === selectedCategory)

  return (
    <div className="space-y-3">
      {/* Dropdown trigger */}
      <div className="relative" ref={ref}>
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-xl border
                      text-sm font-medium transition-all duration-150
                      focus:outline-none focus:ring-2 focus:ring-indigo-400
                      ${selectedCategory
                        ? 'border-indigo-300 bg-indigo-50 text-indigo-800'
                        : 'border-slate-200 bg-white text-slate-500 hover:border-indigo-300 hover:bg-slate-50'}`}
        >
          <span className="flex items-center gap-2.5 min-w-0">
            {selected
              ? <><span className="text-base">{selected.icon}</span><span className="font-semibold truncate">{selected.label}</span></>
              : <><span className="w-5 h-5 rounded bg-slate-200 flex items-center justify-center text-slate-400 flex-shrink-0">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                  </svg>
                </span>
                <span>Select industry…</span>
              </>
            }
          </span>
          <svg className={`w-4 h-4 text-slate-400 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`}
               fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
          </svg>
        </button>

        {/* Dropdown panel */}
        {open && (
          <div className="absolute left-0 right-0 top-full mt-1.5 z-20 bg-white rounded-xl
                          border border-slate-200 shadow-xl overflow-hidden">
            {/* Search */}
            <div className="p-2 border-b border-slate-100">
              <div className="relative">
                <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400"
                     fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
                </svg>
                <input
                  autoFocus
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search industry…"
                  className="w-full pl-8 pr-3 py-2 text-sm border border-slate-200 rounded-lg
                             focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-slate-50"
                />
              </div>
            </div>
            {/* List */}
            <div className="max-h-60 overflow-y-auto py-1">
              {filtered.length === 0
                ? <p className="text-xs text-slate-400 text-center py-4">No industries match "{search}"</p>
                : filtered.map(({ label, icon }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => handleSelect(label)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left
                                transition-colors
                                ${selectedCategory === label
                                  ? 'bg-indigo-50 text-indigo-700 font-semibold'
                                  : 'text-slate-700 hover:bg-slate-50'}`}
                  >
                    <span className="text-base w-5 text-center flex-shrink-0">{icon}</span>
                    <span>{label}</span>
                    {selectedCategory === label && (
                      <svg className="w-3.5 h-3.5 ml-auto text-indigo-600 flex-shrink-0"
                           fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
                      </svg>
                    )}
                  </button>
                ))
              }
            </div>
          </div>
        )}
      </div>

      {/* Quick-pick chips — top 8 most common */}
      <div className="flex flex-wrap gap-1.5">
        {CATEGORIES.slice(0, 8).map(({ label, icon }) => (
          <button
            key={label}
            type="button"
            onClick={() => onSelect(selectedCategory === label ? null : label)}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium
                        border transition-all duration-150
                        focus:outline-none focus:ring-2 focus:ring-indigo-400
                        ${selectedCategory === label
                          ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm'
                          : 'bg-white border-slate-200 text-slate-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700'}`}
          >
            <span>{icon}</span>{label}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-xs font-medium
                     border border-dashed border-slate-300 text-slate-400
                     hover:border-indigo-400 hover:text-indigo-600 hover:bg-indigo-50
                     transition-all focus:outline-none focus:ring-2 focus:ring-indigo-400"
        >
          More…
        </button>
      </div>
    </div>
  )
}

/* ── Location selector ────────────────────────────────────────────────────── */
function LocationSelector({ selectedState, selectedDistrict, onStateChange, onDistrictChange }) {
  const [states,    setStates]    = useState([])
  const [districts, setDistricts] = useState([])
  const [loadStates,   setLoadStates]   = useState(false)
  const [loadDistricts,setLoadDistricts]= useState(false)

  useEffect(() => {
    setLoadStates(true)
    getMapsStates().then(d => setStates(d.states ?? [])).catch(() => {}).finally(() => setLoadStates(false))
  }, [])

  useEffect(() => {
    if (!selectedState) { setDistricts([]); onDistrictChange(''); return }
    setLoadDistricts(true)
    onDistrictChange('')
    getMapsDistricts(selectedState).then(d => setDistricts(d.districts ?? [])).catch(() => {}).finally(() => setLoadDistricts(false))
  }, [selectedState]) // eslint-disable-line react-hooks/exhaustive-deps

  const sel = 'crm-input pr-9 appearance-none'

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {/* State */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-semibold text-slate-500">State <span className="text-rose-400">*</span></label>
        <div className="relative">
          {loadStates && (
            <div className="absolute inset-y-0 right-9 flex items-center">
              <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}
          <select value={selectedState} onChange={e => onStateChange(e.target.value)}
                  disabled={loadStates} className={`${sel} disabled:opacity-60`}>
            <option value="">Select state…</option>
            {states.map(s => <option key={s} value={s}>{s}</option>)}
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
        <label className="text-xs font-semibold text-slate-500">City / District <span className="text-slate-400 font-normal">(optional)</span></label>
        <div className="relative">
          {loadDistricts && (
            <div className="absolute inset-y-0 right-9 flex items-center">
              <svg className="w-4 h-4 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}
          <select value={selectedDistrict} onChange={e => onDistrictChange(e.target.value)}
                  disabled={!selectedState || loadDistricts}
                  className={`${sel} disabled:opacity-50 disabled:cursor-not-allowed`}>
            <option value="">All cities</option>
            {districts.map(d => <option key={d} value={d}>{d}</option>)}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
            <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
            </svg>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Progress bar shown during generation ─────────────────────────────────── */
function GeneratingProgress({ elapsedSeconds, isPolling, polledCount }) {
  const fmtElapsed = (s) => s < 60 ? `${s}s` : `${Math.floor(s/60)}m ${String(s%60).padStart(2,'0')}s`
  return (
    <div className="mt-4 p-4 rounded-xl bg-indigo-50 border border-indigo-200 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse flex-shrink-0"/>
          <span className="text-sm font-semibold text-indigo-700">
            {isPolling ? 'Still processing — collecting results…' : 'Searching for companies…'}
          </span>
        </div>
        <span className="text-xs font-bold text-indigo-600">{fmtElapsed(elapsedSeconds)}</span>
      </div>
      {isPolling && polledCount > 0 && (
        <p className="text-xs text-indigo-600">
          <strong>{polledCount}</strong> leads saved so far — waiting for pipeline to finish…
        </p>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE
   ══════════════════════════════════════════════════════════════════════════════ */
export default function GenerateLeads() {
  const navigate = useNavigate()

  /* ── form state ─────────────────────────────────────────────────────────── */
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedState,    setSelectedState]    = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  const [target,           setTarget]           = useState(10)
  const [sortDir,          setSortDir]          = useState(null)
  const [refreshTick,      setRefreshTick]      = useState(0)

  /* ── reddit state ───────────────────────────────────────────────────────── */
  const [redditLoading, setRedditLoading] = useState(false)
  const [redditLeads,   setRedditLeads]   = useState([])
  const [redditError,   setRedditError]   = useState('')

  /* ── main generation hook ───────────────────────────────────────────────── */
  const {
    leads, isLoading, isPolling, polledCount, elapsedSeconds,
    error, pipelineStats,
    generate, clear,
  } = useGenerateLeads()

  const anyLoading = isLoading || redditLoading
  const ready      = Boolean(selectedCategory && selectedState)
  const allLeads   = useMemo(() => [...leads, ...redditLeads], [leads, redditLeads])

  const sortedLeads = useMemo(() => {
    if (!sortDir) return allLeads
    return [...allLeads].sort((a, b) => {
      const an = (a.company_name ?? '').toLowerCase()
      const bn = (b.company_name ?? '').toLowerCase()
      return sortDir === 'asc' ? an.localeCompare(bn) : bn.localeCompare(an)
    })
  }, [allLeads, sortDir])

  /* ── handlers ───────────────────────────────────────────────────────────── */
  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    if (allLeads.length > 0) { clear(); setRedditLeads([]) }
  }

  const handleRedditGenerate = useCallback(async () => {
    if (!selectedCategory) return
    const location = selectedDistrict
      ? `${selectedDistrict}, ${selectedState}`
      : selectedState || selectedCategory
    setRedditLoading(true)
    setRedditLeads([])
    setRedditError('')
    try {
      const res = await generateRedditLeads({ category: selectedCategory, location, limit: target })
      if (res.success) {
        setRedditLeads(res.leads ?? [])
        setRefreshTick(t => t + 1)
      } else {
        setRedditError(res.message || res.error || 'Lead search failed')
      }
    } catch (err) {
      setRedditError(err.message || 'Search failed')
    } finally {
      setRedditLoading(false)
    }
  }, [selectedCategory, selectedState, selectedDistrict, target])

  const handleGenerate = useCallback(() => {
    if (!ready) return
    clear()
    setRedditLeads([])
    setRedditError('')
    setSortDir(null)
    generate({ industry: selectedCategory, state: selectedState, district: selectedDistrict || null, target })
    handleRedditGenerate()
  }, [ready, selectedCategory, selectedState, selectedDistrict, target, generate, clear, handleRedditGenerate])

  const handleStatusUpdate = useCallback((leadId, newStatus, updatedDoc) => {
    setRefreshTick(t => t + 1)
  }, [])

  const hasResults = allLeads.length > 0

  return (
    <Layout
      followUpRefreshTick={refreshTick}
      onOpenFollowUps={() => navigate('/follow-ups')}
      onNavigateToLead={(lead) => navigate('/', { state: { scrollToLead: lead.id ?? lead._id } })}
    >
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Page header ─────────────────────────────────────────────── */}
        <div className="mb-7">
          <h1 className="text-xl font-bold text-slate-900">Generate Leads</h1>
          <p className="text-sm text-slate-500 mt-1">Find new companies matching your criteria and save them to your CRM.</p>
        </div>

        {/* ── Configuration card ──────────────────────────────────────── */}
        <div className="bg-white rounded-xl border border-slate-200 p-6 mb-6 space-y-7">

          {/* Step 1 — Industry */}
          <div>
            <StepLabel number="1" label="Select Industry" done={!!selectedCategory} />
            <IndustrySelector
              selectedCategory={selectedCategory}
              onSelect={handleCategorySelect}
            />
            {selectedCategory && (
              <p className="mt-2.5 text-xs text-indigo-600 font-medium flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block"/>
                {selectedCategory} selected
              </p>
            )}
          </div>

          <div className="border-t border-slate-100" />

          {/* Step 2 — Location */}
          <div>
            <StepLabel number="2" label="Choose Location" done={!!selectedState} />
            <LocationSelector
              selectedState={selectedState}
              selectedDistrict={selectedDistrict}
              onStateChange={setSelectedState}
              onDistrictChange={setSelectedDistrict}
            />
            {selectedState && (
              <p className="mt-2.5 text-xs text-indigo-600 font-medium flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block"/>
                {selectedDistrict ? `${selectedDistrict}, ${selectedState}` : `All of ${selectedState}`}
              </p>
            )}
          </div>

          <div className="border-t border-slate-100" />

          {/* Step 3 — Number of leads */}
          <div>
            <StepLabel number="3" label="Number of Leads" done={target > 0} />
            <div className="flex items-center gap-3">
              <div className="relative w-44">
                <select value={target} onChange={e => setTarget(Number(e.target.value))}
                        className="crm-input pr-9 appearance-none">
                  {[10, 20, 30, 50, 75, 100, 150, 200].map(n => (
                    <option key={n} value={n}>{n} leads</option>
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

          <div className="border-t border-slate-100" />

          {/* Generate button */}
          <div>
            {!ready && (
              <p className="text-xs text-slate-400 italic mb-3">
                {!selectedCategory ? 'Select an industry above to continue.' : 'Select a state to enable generation.'}
              </p>
            )}
            <button
              onClick={handleGenerate}
              disabled={!ready || anyLoading}
              className={`inline-flex items-center justify-center gap-2.5 px-8 py-3 rounded-xl
                          text-base font-semibold text-white shadow-md transition-all duration-200
                          focus:outline-none focus:ring-4 focus:ring-indigo-300
                          ${!ready || anyLoading
                            ? 'bg-indigo-400 opacity-60 cursor-not-allowed'
                            : 'bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 hover:shadow-lg'}`}
            >
              {anyLoading ? (
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
                  {selectedCategory && <span className="text-sm font-normal opacity-80">— {selectedCategory}</span>}
                </>
              )}
            </button>
            <p className="text-xs text-slate-400 mt-2">
              Find new companies matching your criteria and save them to the CRM.
            </p>

            {/* Progress during generation */}
            {anyLoading && (
              <GeneratingProgress
                elapsedSeconds={elapsedSeconds}
                isPolling={isPolling}
                polledCount={polledCount}
              />
            )}
          </div>
        </div>

        {/* ── Error banners ────────────────────────────────────────────── */}
        {(error || redditError) && (
          <ErrorBanner message={error || redditError} />
        )}

        {/* ── Pipeline stats ───────────────────────────────────────────── */}
        {pipelineStats && !anyLoading && (
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-4 py-3
                          rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-500 mb-4">
            <span className="font-semibold text-slate-600 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"/>
              Run complete
            </span>
            <span>Discovered: <strong className="text-slate-700">{pipelineStats.google_maps_discovered ?? 0}</strong></span>
            <span>Saved: <strong className="text-slate-700">{pipelineStats.final_valid_companies ?? pipelineStats.google_maps_discovered ?? 0}</strong></span>
            {(pipelineStats.elapsed_seconds != null) && (
              <span>Time: <strong>{pipelineStats.elapsed_seconds}s</strong></span>
            )}
          </div>
        )}

        {/* ── Results table ────────────────────────────────────────────── */}
        {(hasResults || isLoading) && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-700">
                {hasResults ? `${allLeads.length} leads found` : 'Finding leads…'}
              </h2>
              {hasResults && (
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSortDir(d => d === 'asc' ? 'desc' : d === 'desc' ? null : 'asc')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold
                               border border-slate-200 rounded-lg bg-white text-slate-600
                               hover:bg-slate-50 transition-colors">
                    Sort {sortDir === 'asc' ? '↑' : sortDir === 'desc' ? '↓' : '↕'}
                  </button>
                  <a href={`/leads`}
                    className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">
                    View all leads →
                  </a>
                </div>
              )}
            </div>
            <LeadsTable
              leads={sortedLeads}
              isLoading={isLoading && allLeads.length === 0}
              onStatusUpdate={handleStatusUpdate}
              sortDir={sortDir}
              onSortChange={() => setSortDir(d => d === 'asc' ? 'desc' : d === 'desc' ? null : 'asc')}
            />
          </div>
        )}
      </div>
    </Layout>
  )
}
