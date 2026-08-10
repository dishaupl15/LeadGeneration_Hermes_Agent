/**
 * Empty / no-results illustration shown inside the table.
 * Props:
 *   title       – string (optional)
 *   description – string (optional)
 *   icon        – 'default' | 'search' | 'error' (optional)
 */
export default function EmptyState({
  title = 'No leads generated yet.',
  description = 'Pick an industry category above and hit "Generate Leads" to populate this table.',
  icon = 'default',
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center fade-in-up">
      {/* Illustration circle */}
      <div className="relative mb-6">
        <div className="w-24 h-24 rounded-full bg-indigo-50 flex items-center justify-center">
          {icon === 'search' ? (
            <svg className="w-10 h-10 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          ) : icon === 'error' ? (
            <svg className="w-10 h-10 text-rose-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
          ) : (
            <svg className="w-10 h-10 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
            </svg>
          )}
        </div>
        {/* Decorative dots */}
        <span className="absolute top-1 right-1 w-3 h-3 bg-indigo-200 rounded-full" />
        <span className="absolute bottom-2 left-0 w-2 h-2 bg-indigo-100 rounded-full" />
      </div>

      <h3 className="text-lg font-semibold text-slate-700 mb-2">{title}</h3>
      <p className="text-sm text-slate-400 max-w-xs leading-relaxed">{description}</p>
    </div>
  )
}
