/**
 * RefreshLeadsButton
 *
 * Calls GET /leads to reload MongoDB data without triggering Hermes.
 *
 * Props:
 *   isRefreshing – boolean   — shows spinner while in flight
 *   isLoading    – boolean   — disabled while generate is running
 *   onClick      – () => void
 */
export default function RefreshLeadsButton({ isRefreshing, isLoading, onClick }) {
  const disabled = isRefreshing || isLoading

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label="Refresh leads from database"
      title="Reload all leads directly from MongoDB — no AI, no scraping"
      className={`
        inline-flex items-center gap-2 px-4 py-2.5 rounded-xl
        border border-slate-200 bg-white text-slate-600 text-sm font-medium
        shadow-sm hover:bg-slate-50 hover:border-slate-300 hover:text-slate-800
        transition-all duration-150
        disabled:opacity-50 disabled:cursor-not-allowed disabled:pointer-events-none
      `}
    >
      {/* Rotate icon while refreshing */}
      <svg
        className={`w-4 h-4 flex-shrink-0 ${isRefreshing ? 'animate-spin' : ''}`}
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
      <span>{isRefreshing ? 'Refreshing…' : 'Refresh Leads'}</span>

      {/* DB badge — visible when idle */}
      {!isRefreshing && (
        <span className="
          hidden sm:inline-flex items-center gap-1
          px-1.5 py-0.5 rounded text-[10px] font-semibold
          bg-emerald-50 text-emerald-600 border border-emerald-200
        ">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block" />
          DB
        </span>
      )}
    </button>
  )
}
