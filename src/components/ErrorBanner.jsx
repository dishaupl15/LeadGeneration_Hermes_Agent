/**
 * ErrorBanner
 *
 * Displayed below the Generate button when an API call fails.
 * Shows the error message, a Retry action, and a dismiss (×) button.
 *
 * Props:
 *   message  – string   — human-readable error from the API layer
 *   onRetry  – () => void — re-fires the last request
 *   onDismiss – () => void — clears the error
 */
export default function ErrorBanner({ message, onRetry, onDismiss }) {
  return (
    <div
      role="alert"
      className="
        flex items-start gap-3 mb-6 px-4 py-4 rounded-xl
        bg-rose-50 border border-rose-200 text-rose-800
        fade-in-up
      "
    >
      {/* Icon */}
      <div className="flex-shrink-0 mt-0.5">
        <svg className="w-5 h-5 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
        </svg>
      </div>

      {/* Message */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-rose-800 mb-0.5">Request Failed</p>
        <p className="text-sm text-rose-700 leading-relaxed">{message}</p>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 flex-shrink-0">
        {onRetry && (
          <button
            onClick={onRetry}
            className="
              inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg
              text-xs font-semibold text-rose-700
              bg-rose-100 hover:bg-rose-200 border border-rose-200
              transition-colors
            "
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            Retry
          </button>
        )}

        <button
          onClick={onDismiss}
          aria-label="Dismiss error"
          className="
            w-7 h-7 flex items-center justify-center rounded-full
            text-rose-400 hover:text-rose-600 hover:bg-rose-100
            transition-colors
          "
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  )
}
