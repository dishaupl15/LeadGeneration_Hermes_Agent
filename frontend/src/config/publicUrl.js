/**
 * publicUrl.js
 * ────────────
 * Single source of truth for building public form URLs.
 *
 * Usage:
 *   import { getPublicFormUrl } from '../config/publicUrl'
 *   const url = getPublicFormUrl(formId)
 *   // → "https://your-domain.com/f/abc123"
 *
 * Resolution order (evaluated once at module load):
 *   1. VITE_PUBLIC_APP_URL  — explicit production/staging override
 *   2. VITE_PUBLIC_FORM_BASE_URL — legacy alias (kept for backwards compat)
 *   3. window.location.origin   — auto-detect at runtime (works for local dev
 *                                  from any hostname/IP without any .env change)
 *
 * Rules:
 *   • Never hardcode any IP address, port, or domain in this file.
 *   • All values come from environment variables or the browser's own origin.
 *   • The returned URL never has a trailing slash.
 *
 * Environment variables (set in frontend/.env):
 *
 *   Development — no configuration needed. The app uses window.location.origin
 *   automatically, so public links open on the same host/IP the CRM is running on.
 *
 *   Production — REQUIRED:
 *     VITE_PUBLIC_APP_URL=https://your-frontend-domain.com
 *
 *   Legacy (still supported, lower priority than VITE_PUBLIC_APP_URL):
 *     VITE_PUBLIC_FORM_BASE_URL=https://your-frontend-domain.com
 */

// Evaluate once so all callers share the same resolved base.
const _resolveBase = () => {
  // 1. Explicit production override (preferred env var name)
  const explicit =
    import.meta.env.VITE_PUBLIC_APP_URL ||
    import.meta.env.VITE_PUBLIC_FORM_BASE_URL

  if (explicit && explicit.trim()) {
    return explicit.trim().replace(/\/$/, '')
  }

  // 2. Auto-detect from browser (works for any hostname/IP in dev)
  if (typeof window !== 'undefined') {
    return window.location.origin
  }

  // 3. SSR/build-time fallback (should never reach here in practice)
  return 'http://localhost:5173'
}

export const PUBLIC_APP_BASE = _resolveBase()

/**
 * Build a shareable public form URL for the given form ID / slug.
 *
 * @param {string} formId  — the form's unique ID or slug
 * @returns {string}       — e.g. "https://your-domain.com/f/abc123"
 */
export function getPublicFormUrl(formId) {
  return `${PUBLIC_APP_BASE}/f/${encodeURIComponent(formId)}`
}

/**
 * Build a campaign tracking URL (includes UTM-style params).
 *
 * @param {string} formId
 * @param {string} platform    — e.g. "linkedin"
 * @param {string} campaignId
 * @returns {string}
 */
export function getCampaignTrackingUrl(formId, platform, campaignId) {
  const base = getPublicFormUrl(formId)
  const params = new URLSearchParams()
  if (platform)   params.set('source',      platform)
  if (campaignId) params.set('campaign_id', campaignId)
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}
