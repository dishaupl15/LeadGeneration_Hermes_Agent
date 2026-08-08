/**
 * Search box + Refresh button row above the leads table.
 * Props:
 *   value        – string
 *   onChange     – (v: string) => void
 *   onRefresh    – () => void
 *   isLoading    – boolean
 *   totalResults – number
 */
export default function SearchBar({ value, onChange, onRefresh, isLoading, totalResults }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">

      {/* Search input */}
      <div className="relative flex-1">
        {/* Magnifier icon */}
        <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3.5">
          <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search by company name…"
          className="crm-input pl-10 pr-10"
        />

        {/* Clear button */}
        {value && (
          <button
            onClick={() => onChange('')}
            aria-label="Clear search"
            className="
              absolute inset-y-0 right-0 flex items-center pr-3
              text-slate-400 hover:text-slate-600 transition-colors
            "
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {/* Result count badge */}
      {totalResults > 0 && (
        <span className="hidden sm:inline-flex items-center px-3 py-1 rounded-full bg-indigo-50 text-indigo-600 text-xs font-semibold whitespace-nowrap border border-indigo-100">
          {totalResults} lead{totalResults !== 1 ? 's' : ''}
        </span>
      )}

      {/* Refresh button */}
      <button
        onClick={onRefresh}
        disabled={isLoading}
        aria-label="Refresh leads"
        className="btn-secondary px-4 py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <svg
          className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        Refresh
      </button>
    </div>
  )
}
