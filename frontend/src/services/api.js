/**
 * API service layer — all network calls live here.
 *
 * Keeping fetch logic out of components means:
 *  - One place to change the base URL
 *  - One place to add auth headers later
 *  - Components stay clean and testable
 */

const BASE_URL = 'http://localhost:8002'

/**
 * Shared fetch wrapper.
 * Throws a structured Error on non-2xx responses so callers get a
 * consistent error shape regardless of whether the backend returned
 * a JSON error body or a network-level failure.
 *
 * @param {string} path      - API path e.g. "/leads/generate-leads"
 * @param {RequestInit} opts - Standard fetch options
 * @returns {Promise<any>}   - Parsed JSON response body
 */
async function apiFetch(path, opts = {}) {
  const url = `${BASE_URL}${path}`

  // 10-minute timeout — with 10 companies × 6 pages each, the pipeline can
  // take 4–8 minutes (Serper + Firecrawl scraping + Enrich + Verify stages).
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10 * 60 * 1000)

  let response
  try {
    response = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...opts.headers },
      signal: controller.signal,
      ...opts,
    })
  } catch (networkError) {
    clearTimeout(timer)
    if (networkError.name === 'AbortError') {
      throw new Error('Request timed out after 10 minutes. The backend may still be processing.')
    }
    throw new Error(
      `Cannot reach the server. Make sure the backend is running on ${BASE_URL}`
    )
  } finally {
    clearTimeout(timer)
  }

  if (!response.ok) {
    // Try to pull a meaningful message out of the FastAPI error body
    let detail = `Request failed (HTTP ${response.status})`
    try {
      const errBody = await response.json()
      if (errBody?.detail) {
        detail = Array.isArray(errBody.detail)
          ? errBody.detail.map((e) => e.msg).join(', ')
          : errBody.detail
      }
    } catch {
      // Response body wasn't JSON — use the status text
      detail = response.statusText || detail
    }
    throw new Error(detail)
  }

  return response.json()
}

// ── Lead Generation ──────────────────────────────────────────────────────────

/**
 * POST /leads/generate-leads
 *
 * Sends { industry, city, count }, Hermes generates leads, backend upserts
 * to MongoDB, then returns the actual MongoDB documents.
 *
 * @param {{ industry: string, city: string, count?: number }} params
 * @returns {Promise<{
 *   success:   boolean,
 *   inserted:  number,
 *   updated:   number,
 *   total:     number,
 *   query:     string,
 *   timestamp: string,
 *   leads:     Array<{
 *     id:           string,
 *     company_name: string,
 *     website:      string,
 *     emails:       string[],
 *     phones:       string[],
 *     address:      string,
 *     city:         string,
 *     state:        string,
 *     country:      string,
 *     created_at:   string,
 *     updated_at:   string
 *   }>
 * }>}
 */
export async function generateLeads({ industry, city, count = 10 }) {
  return apiFetch('/leads/generate-leads', {
    method: 'POST',
    body: JSON.stringify({ industry, city, count }),
  })
}

// ── Other endpoints (ready for future use) ───────────────────────────────────

/**
 * GET /leads  — list all stored leads with optional filters
 * @param {{ category?: string, search?: string, page?: number, per_page?: number }} params
 */
export async function getLeads(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
  ).toString()
  return apiFetch(`/leads${qs ? `?${qs}` : ''}`)
}

/**
 * GET /  — health check
 */
export async function healthCheck() {
  return apiFetch('/')
}
