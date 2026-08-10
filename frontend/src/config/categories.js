/**
 * categories.js
 * -------------
 * Single source of truth for all industry categories.
 *
 * To add, remove, or reorder categories — edit this file only.
 * Both the category pill bar and the stats card read from here automatically.
 *
 * Each entry:
 *   label  – display name shown on the pill and passed to the API as `industry`
 *   icon   – emoji rendered inside the pill
 */

export const CATEGORIES = [
  { label: 'Technology',          icon: '💡' },
  { label: 'SaaS',                icon: '☁️' },
  { label: 'AI',                  icon: '🤖' },
  { label: 'FinTech',             icon: '💳' },
  { label: 'Healthcare',          icon: '🏥' },
  { label: 'Pharma',              icon: '💊' },
  { label: 'Manufacturing',       icon: '🏭' },
  { label: 'Construction',        icon: '🏗️' },
  { label: 'Real Estate',         icon: '🏠' },
  { label: 'Education',           icon: '🎓' },
  { label: 'Logistics',           icon: '🚚' },
  { label: 'Automotive',          icon: '🚗' },
  { label: 'Retail',              icon: '🏪' },
  { label: 'E-Commerce',          icon: '🛒' },
  { label: 'Hospitality',         icon: '🏨' },
  { label: 'Travel',              icon: '✈️' },
  { label: 'Energy',              icon: '⚡' },
  { label: 'Agriculture',         icon: '🌾' },
  { label: 'Media',               icon: '📺' },
  { label: 'Marketing',           icon: '📣' },
  { label: 'Consulting',          icon: '🤝' },
  { label: 'Legal',               icon: '⚖️' },
  { label: 'Finance',             icon: '💰' },
  { label: 'Insurance',           icon: '🛡️' },
  { label: 'Telecommunications',  icon: '📡' },
  { label: 'Cybersecurity',       icon: '🔒' },
  { label: 'Biotech',             icon: '🧬' },
  { label: 'Aerospace',           icon: '🚀' },
]

/** Plain string array — used wherever only the label is needed. */
export const CATEGORY_LABELS = CATEGORIES.map((c) => c.label)
