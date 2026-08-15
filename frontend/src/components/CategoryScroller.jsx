import { useRef } from 'react'
import { CATEGORIES } from '../config/categories'

/**
 * Horizontally scrollable category pill bar with left/right arrow buttons.
 *
 * Categories are read from src/config/categories.js — no hardcoded list here.
 *
 * Props:
 *   selectedCategory – string | null
 *   onSelectCategory – (label: string) => void
 */
export default function CategoryScroller({ selectedCategory, onSelectCategory }) {
  const scrollRef = useRef(null)

  const scroll = (dir) => {
    if (!scrollRef.current) return
    scrollRef.current.scrollBy({ left: dir === 'left' ? -220 : 220, behavior: 'smooth' })
  }

  return (
    <div className="crm-card p-4">
      {/* Section label */}
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-2.5 px-1">
        Select Industry
      </p>

      <div className="flex items-center gap-2">
        {/* Left arrow */}
        <button
          onClick={() => scroll('left')}
          aria-label="Scroll categories left"
          className="
            flex-shrink-0 w-9 h-9 flex items-center justify-center
            rounded-full border border-slate-200 bg-white text-slate-500
            hover:bg-indigo-50 hover:border-indigo-300 hover:text-indigo-600
            active:scale-95 transition-all duration-150 shadow-sm
          "
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        {/* Scrollable pill list — rendered from config */}
        <div
          ref={scrollRef}
          className="flex-1 flex gap-2 overflow-x-auto scrollbar-hide py-1"
        >
          {CATEGORIES.map(({ label, icon }) => {
            const active = selectedCategory === label
            return (
              <button
                key={label}
                onClick={() => onSelectCategory(label)}
                className={`
                  flex-shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-full
                  text-sm font-medium transition-all duration-200 whitespace-nowrap
                  focus:outline-none focus:ring-2 focus:ring-indigo-400
                  ${active
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200 scale-105'
                    : 'bg-slate-100 text-slate-600 hover:bg-indigo-50 hover:text-indigo-700 border border-transparent hover:border-indigo-200'
                  }
                `}
              >
                <span className="text-base leading-none">{icon}</span>
                {label}
              </button>
            )
          })}
        </div>

        {/* Right arrow */}
        <button
          onClick={() => scroll('right')}
          aria-label="Scroll categories right"
          className="
            flex-shrink-0 w-9 h-9 flex items-center justify-center
            rounded-full border border-slate-200 bg-white text-slate-500
            hover:bg-indigo-50 hover:border-indigo-300 hover:text-indigo-600
            active:scale-95 transition-all duration-150 shadow-sm
          "
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      {/* Selected indicator */}
      {selectedCategory && (
        <div className="mt-3 px-1 flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 inline-block" />
          <span className="text-xs text-indigo-600 font-medium">
            {selectedCategory} selected
          </span>
        </div>
      )}
    </div>
  )
}
