/**
 * LocationSelector
 *
 * State + district dropdowns for the Google Maps search panel.
 * Districts load dynamically from the backend when a state is selected.
 *
 * Props:
 *   states           – string[]
 *   districts        – string[]
 *   loadingStates    – boolean
 *   loadingDistricts – boolean
 *   selectedState    – string
 *   selectedDistrict – string
 *   onStateChange    – (state: string) => void
 *   onDistrictChange – (district: string) => void
 *   target           – number
 *   onTargetChange   – (n: number) => void
 *   excludeSeen      – boolean
 *   onExcludeSeenChange – (b: boolean) => void
 */
export default function LocationSelector({
  states,
  districts,
  loadingStates,
  loadingDistricts,
  selectedState,
  selectedDistrict,
  onStateChange,
  onDistrictChange,
  target,
  onTargetChange,
  excludeSeen,
  onExcludeSeenChange,
}) {
  return (
    <div className="crm-card p-5 mb-6">
      {/* Section label */}
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4 px-0.5">
        🗺️ Search Location
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">

        {/* ── State ── */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            State <span className="text-rose-400">*</span>
          </label>
          <div className="relative">
            {loadingStates && (
              <div className="absolute inset-y-0 right-9 flex items-center pr-1">
                <svg className="w-4 h-4 animate-spin text-indigo-400"
                  fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" strokeWidth="4"/>
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
              {states.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            {/* Chevron */}
            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
              <svg className="w-4 h-4 text-slate-400" fill="none"
                stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  strokeWidth={2} d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </div>
        </div>

        {/* ── District ── */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            District
            <span className="ml-1 text-slate-400 font-normal">(optional — searches whole state if blank)</span>
          </label>
          <div className="relative">
            {loadingDistricts && (
              <div className="absolute inset-y-0 right-9 flex items-center pr-1">
                <svg className="w-4 h-4 animate-spin text-indigo-400"
                  fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10"
                    stroke="currentColor" strokeWidth="4"/>
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
              {districts.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            {/* Chevron */}
            <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
              <svg className="w-4 h-4 text-slate-400" fill="none"
                stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                  strokeWidth={2} d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
          </div>
        </div>

        {/* ── Target count ── */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            Target companies
          </label>
          <select
            value={target}
            onChange={(e) => onTargetChange(Number(e.target.value))}
            className="crm-input pr-9 appearance-none"
          >
            {[10, 20, 30, 50, 75, 100, 150, 200].map((n) => (
              <option key={n} value={n}>{n} companies</option>
            ))}
          </select>
        </div>

        {/* ── Exclude seen ── */}
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-semibold text-slate-600">
            Deduplication
          </label>
          <button
            type="button"
            onClick={() => onExcludeSeenChange(!excludeSeen)}
            className={`
              h-[42px] rounded-xl border text-sm font-medium
              inline-flex items-center gap-2 px-4
              transition-all duration-200 shadow-sm
              ${excludeSeen
                ? 'bg-emerald-50 border-emerald-300 text-emerald-700 hover:bg-emerald-100'
                : 'bg-slate-50 border-slate-300 text-slate-500 hover:bg-slate-100'
              }
            `}
          >
            {/* Toggle pill */}
            <span className={`
              w-8 h-4 rounded-full relative flex-shrink-0
              transition-colors duration-200
              ${excludeSeen ? 'bg-emerald-500' : 'bg-slate-300'}
            `}>
              <span className={`
                absolute top-0.5 w-3 h-3 rounded-full bg-white shadow
                transition-transform duration-200
                ${excludeSeen ? 'translate-x-4' : 'translate-x-0.5'}
              `}/>
            </span>
            {excludeSeen ? 'Skip seen businesses' : 'Include all results'}
          </button>
        </div>
      </div>

      {/* ── Location summary badge ── */}
      {selectedState && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full
                           bg-indigo-50 border border-indigo-200 text-indigo-700
                           text-xs font-semibold">
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"/>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
            </svg>
            {selectedDistrict
              ? `${selectedDistrict}, ${selectedState}`
              : `${selectedState} (all districts)`
            }
          </span>
          <span className="text-xs text-slate-400">
            · target {target} companies via Google Maps
          </span>
        </div>
      )}
    </div>
  )
}
