/**
 * GoogleMapsPanel
 *
 * Complete UI panel for the Google Maps lead-discovery tab.
 * Uses the LocationSelector, CategoryScroller, and MapsLeadsTable.
 *
 * Props:
 *   hook – return value of useGoogleMapsLeads()
 */

import { useState, useMemo } from 'react'
import { CATEGORIES } from '../config/categories'
import LocationSelector from './LocationSelector'
import MapsLeadsTable from './MapsLeadsTable'

/* ── Category pill scroller (re-used layout, Maps-specific color) ──────── */
function MapsCategoryScroller({ selectedCategory, onSelect }) {
  return (
    <div className="crm-card p-4 mb-6">
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 px-0.5">
        Select Industry
      </p>
      <div className="flex gap-2 overflow-x-auto scrollbar-hide py-1">
        {CATEGORIES.map(({ label, icon }) => {
          const active = selectedCategory === label
          return (
            <button
              key={label}
              onClick={() => onSelect(label)}
              className={`
                flex-shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-full
                text-sm font-medium transition-all duration-200 whitespace-nowrap
                focus:outline-none focus:ring-2 focus:ring-emerald-400
                ${active
                  ? 'bg-emerald-600 text-white shadow-md shadow-emerald-200 scale-105'
                  : 'bg-slate-100 text-slate-600 hover:bg-emerald-50 hover:text-emerald-700 border border-transparent hover:border-emerald-200'
                }
              `}
            >
              <span className="text-base leading-none">{icon}</span>
              {label}
            </button>
          )
        })}
      </div>
      {selectedCategory && (
        <div className="mt-3 px-0.5 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block"/>
          <span className="text-xs text-emerald-600 font-medium">{selectedCategory} selected</span>
        </div>
      )}
    </div>
  )
}

/* ── Search button ──────────────────────────────────────────────────────── */
function SearchButton({ ready, isLoading, onClick, selectedCategory }) {
  const disabled = !ready || isLoading
  return (
    <div className="flex flex-col items-center gap-3 mb-8">
      {!ready && (
        <p className="text-sm text-slate-400 italic">
          📍 Select a category and state to search businesses
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
            ? 'bg-emerald-400 opacity-60 cursor-not-allowed pointer-events-none'
            : 'bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 hover:shadow-lg cursor-pointer'
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
              <circle className="opacity-25" cx="12" cy="12" r="10"
                stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
            </svg>
            Searching Google Maps…
          </>
        ) : (
          <>
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
            Search Businesses
            {selectedCategory && (
              <span className="text-sm font-normal text-emerald-200">— {selectedCategory}</span>
            )}
          </>
        )}
      </button>
      {isLoading ? (
        <p className="text-xs text-emerald-500 animate-pulse font-medium">
          ⏳ Querying Google Places API across localities…
        </p>
      ) : (
        <p className="text-xs text-slate-400">
          Powered by Google Places API (New) · Results deduplicated by Place ID
        </p>
      )}
    </div>
  )
}

/* ── Main panel ─────────────────────────────────────────────────────────── */
export default function GoogleMapsPanel({ hook }) {
  const {
    states, districts, loadingStates, loadingDistricts,
    selectedState, setSelectedState,
    selectedDistrict, setSelectedDistrict,
    target, setTarget,
    excludeSeen, setExcludeSeen,
    businesses, stats, pipelineStats, isLoading, error,
    search, clear,
  } = hook

  const [selectedCategory, setSelectedCategory] = useState(null)
  const [searchQuery, setSearchQuery]           = useState('')

  const handleCategorySelect = (cat) => {
    setSelectedCategory(cat)
    if (businesses.length > 0) clear()
    setSearchQuery('')
  }

  const handleSearch = () => {
    if (!selectedCategory || !selectedState) return
    setSearchQuery('')
    search(selectedCategory)
  }

  const ready = Boolean(selectedCategory && selectedState)

  // client-side search filter
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return businesses
    const q = searchQuery.toLowerCase()
    return businesses.filter(
      (b) =>
        (b.name ?? '').toLowerCase().includes(q) ||
        (b.address ?? '').toLowerCase().includes(q) ||
        (b.search_area ?? '').toLowerCase().includes(q)
    )
  }, [businesses, searchQuery])

  return (
    <div>
      {/* Category */}
      <MapsCategoryScroller
        selectedCategory={selectedCategory}
        onSelect={handleCategorySelect}
      />

      {/* Location + config */}
      <LocationSelector
        states={states}
        districts={districts}
        loadingStates={loadingStates}
        loadingDistricts={loadingDistricts}
        selectedState={selectedState}
        selectedDistrict={selectedDistrict}
        onStateChange={setSelectedState}
        onDistrictChange={setSelectedDistrict}
        target={target}
        onTargetChange={setTarget}
        excludeSeen={excludeSeen}
        onExcludeSeenChange={setExcludeSeen}
      />

      {/* Search button */}
      <SearchButton
        ready={ready}
        isLoading={isLoading}
        onClick={handleSearch}
        selectedCategory={selectedCategory}
      />

      {/* Error */}
      {error && (
        <div className="mb-6 p-4 rounded-xl bg-rose-50 border border-rose-200
                        text-rose-700 text-sm flex items-start gap-3">
          <svg className="w-5 h-5 flex-shrink-0 mt-0.5" fill="none"
            stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <div>
            <p className="font-medium">Search failed</p>
            <p className="mt-0.5 text-rose-600">{error}</p>
          </div>
          <button onClick={clear}
            className="ml-auto text-rose-400 hover:text-rose-600 flex-shrink-0">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      )}

      {/* Results card */}
      <div className="crm-card p-5 sm:p-6">
        {/* Header row */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-5">
          <div>
            <h2 className="text-base font-bold text-slate-800">
              Google Maps Businesses
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              {isLoading
                ? 'Searching businesses via Google Places API…'
                : businesses.length === 0
                  ? 'No results yet — configure your search and click Search Businesses.'
                  : `${filtered.length} of ${businesses.length} unique business${businesses.length !== 1 ? 'es' : ''}`
                    + (selectedState ? ` · ${selectedDistrict ? selectedDistrict + ', ' : ''}${selectedState}` : '')
              }
            </p>
          </div>

          {businesses.length > 0 && (
            <div className="flex items-center gap-2 self-start sm:self-auto">
              {/* Stats chips */}
              {stats && (
                <>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                                   bg-emerald-50 border border-emerald-200 text-emerald-700
                                   text-xs font-semibold">
                    📞 {stats.with_phone} phones
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full
                                   bg-sky-50 border border-sky-200 text-sky-700
                                   text-xs font-semibold">
                    🌐 {stats.with_website} websites
                  </span>
                </>
              )}
            </div>
          )}
        </div>

        {/* Search bar */}
        <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
          <div className="relative flex-1">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5">
              <svg className="w-4 h-4 text-slate-400" fill="none"
                stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
              </svg>
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by name, address, or area…"
              className="crm-input pl-10 pr-10"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery('')}
                className="absolute inset-y-0 right-0 flex items-center pr-3
                           text-slate-400 hover:text-slate-600 transition-colors">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"/>
                </svg>
              </button>
            )}
          </div>
          {filtered.length > 0 && (
            <span className="hidden sm:inline-flex items-center px-3 py-1 rounded-full
                             bg-emerald-50 text-emerald-600 text-xs font-semibold
                             border border-emerald-100 whitespace-nowrap">
              {filtered.length} result{filtered.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {/* Table */}
        <MapsLeadsTable
          businesses={filtered}
          isLoading={isLoading}
          searchQuery={searchQuery}
          stats={stats}
          pipelineStats={pipelineStats}
        />
      </div>
    </div>
  )
}
