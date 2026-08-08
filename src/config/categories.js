/**
 * categories.js
 * -------------
 * Single source of truth for all industry categories.
 *
 * To add, remove, or reorder categories — edit this file only.
 * Both the category pill bar and the stats card read from here automatically.
 *
 * Each entry:
 *   label  – display name shown on the pill and passed to the API
 *   icon   – emoji rendered inside the pill
 */

export const CATEGORIES = [
  { label: 'Real Estate',            icon: '🏠' },
  { label: 'IT',                     icon: '🖥️' },
  { label: 'Software',               icon: '💻' },
  { label: 'Healthcare',             icon: '🏥' },
  { label: 'Education',              icon: '🎓' },
  { label: 'Manufacturing',          icon: '🏭' },
  { label: 'E-Commerce',             icon: '🛒' },
  { label: 'Finance',                icon: '💰' },
  { label: 'Marketing',              icon: '📣' },
  { label: 'Logistics',              icon: '🚚' },
]

/** Plain string array — used wherever only the label is needed. */
export const CATEGORY_LABELS = CATEGORIES.map((c) => c.label)
