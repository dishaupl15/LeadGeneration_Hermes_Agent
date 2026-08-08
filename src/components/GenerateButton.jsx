/**
 * GenerateButton
 *
 * Primary CTA that triggers lead generation.
 *
 * Props:
 *   selectedCategory – string | null   — disables button when null
 *   isLoading        – boolean         — disables button + shows spinner
 *   onClick          – () => void
 */

import { useState, useEffect } from 'react'

const LOADING_STEPS = [
  'Searching Google via Serper…',
  'Scraping company websites…',
  'Extracting contact info…',
  'Saving to database…',
]

export default function GenerateButton({ selectedCategory, isLoading, onClick }) {
  const disabled = isLoading || !selectedCategory
  const [stepIndex, setStepIndex] = useState(0)

  // Cycle through status messages while loading
  useEffect(() => {
    if (!isLoading) { setStepIndex(0); return }
    const interval = setInterval(() => {
      setStepIndex(i => (i + 1) % LOADING_STEPS.length)
    }, 4000)
    return () => clearInterval(interval)
  }, [isLoading])

  return (
    <div className="flex flex-col items-center gap-3 mb-8">

      {/* Hint — only shown when no category is chosen */}
      {!selectedCategory && (
        <p className="text-sm text-slate-400 italic">
          💡 Select a category above to target your leads
        </p>
      )}

      <button
        onClick={onClick}
        disabled={disabled}
        aria-disabled={disabled}
        className={`
          btn-primary px-12 py-4 text-lg
          relative overflow-hidden group
          transition-all duration-200
          ${disabled
            ? 'opacity-50 cursor-not-allowed pointer-events-none'
            : 'cursor-pointer'}
        `}
      >
        {/* Shimmer sweep on hover (only when enabled) */}
        {!disabled && (
          <span
            className="
              absolute inset-0 bg-white/20 translate-x-[-100%]
              group-hover:translate-x-[100%] transition-transform duration-700
              ease-in-out skew-x-[-15deg] pointer-events-none
            "
          />
        )}

        {isLoading ? (
          /* ── Loading state ── */
          <>
            <svg
              className="w-5 h-5 animate-spin flex-shrink-0"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12" cy="12" r="10"
                stroke="currentColor" strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v8H4z"
              />
            </svg>
            <span>Generating Leads…</span>
          </>
        ) : (
          /* ── Default / ready state ── */
          <>
            <svg
              className="w-5 h-5"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                d="M13 10V3L4 14h7v7l9-11h-7z"
              />
            </svg>
            <span>Generate Leads</span>
            {selectedCategory && (
              <span className="text-sm font-normal text-indigo-200">
                — {selectedCategory}
              </span>
            )}
          </>
        )}
      </button>

      {/* Sub-caption / live status */}
      {isLoading ? (
        <p className="text-xs text-indigo-400 animate-pulse font-medium">
          ⏳ {LOADING_STEPS[stepIndex]}
        </p>
      ) : (
        <p className="text-xs text-slate-400">
          Powered by Serper + Firecrawl · Results will appear in the table below
        </p>
      )}
    </div>
  )
}
