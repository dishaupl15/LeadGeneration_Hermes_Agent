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
 * Google Maps-first pipeline:
 *   Google Maps Discovery → CompanyEnrich → Serper → Firecrawl → MongoDB
 *
 * @param {{
 *   industry: string,
 *   state:    string,
 *   district?: string | null,
 *   target?:  number,
 * }} params
 * @returns {Promise<{
 *   success:        boolean,
 *   inserted:       number,
 *   updated:        number,
 *   total:          number,
 *   query:          string,
 *   timestamp:      string,
 *   pipeline_stats: object,
 *   leads:          Array<object>
 * }>}
 */
export async function generateLeads({ industry, state, district = null, target = 10 }) {
  return apiFetch('/leads/generate-leads', {
    method: 'POST',
    body: JSON.stringify({ industry, state, district: district || null, target }),
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

// ── Google Maps module ───────────────────────────────────────────────────────

/**
 * GET /maps-leads/states
 * Returns the list of Indian states supported by the Google Maps module.
 * @returns {Promise<{ states: string[] }>}
 */
export async function getMapsStates() {
  return apiFetch('/maps-leads/states')
}

/**
 * GET /maps-leads/districts/{state}
 * Returns districts for a given state.
 * @param {string} state
 * @returns {Promise<{ state: string, districts: string[] }>}
 */
export async function getMapsDistricts(state) {
  return apiFetch(`/maps-leads/districts/${encodeURIComponent(state)}`)
}

/**
 * POST /maps-leads/generate
 * Discover businesses from Google Maps for the given category + geography.
 *
 * @param {{
 *   category:     string,
 *   state:        string,
 *   district?:    string | null,
 *   target?:      number,
 *   exclude_seen?: boolean,
 * }} params
 * @returns {Promise<{
 *   success:    boolean,
 *   category:   string,
 *   state:      string,
 *   district:   string | null,
 *   target:     number,
 *   total:      number,
 *   message:    string,
 *   businesses: Array<{
 *     place_id:        string,
 *     name:            string,
 *     address:         string,
 *     phone:           string | null,
 *     website:         string | null,
 *     google_maps_uri: string | null,
 *     primary_type:    string | null,
 *     latitude:        number | null,
 *     longitude:       number | null,
 *     source:          string,
 *     search_query:    string,
 *     search_area:     string,
 *   }>,
 *   stats: {
 *     total_api_calls:    number,
 *     total_raw_results:  number,
 *     duplicates_removed: number,
 *     with_phone:         number,
 *     with_website:       number,
 *     areas_searched:     number,
 *     queries_executed:   number,
 *     elapsed_seconds:    number,
 *     target_reached:     boolean,
 *     exhausted:          boolean,
 *   }
 * }>}
 */
export async function generateMapsLeads({ category, state, district, target = 50, exclude_seen = true }) {
  return apiFetch('/maps-leads/generate', {
    method: 'POST',
    body: JSON.stringify({ category, state, district: district || null, target, exclude_seen }),
  })
}

// ── Generation History ────────────────────────────────────────────────────────

/**
 * GET /history
 * List all generation runs, newest first.
 * @param {{ category?: string, status?: string, page?: number, per_page?: number }} params
 */
export async function getHistory(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
  ).toString()
  return apiFetch(`/history${qs ? `?${qs}` : ''}`)
}

/**
 * GET /history/legacy
 * List legacy categories with lead counts (leads stored before history feature).
 */
export async function getLegacyCategories() {
  return apiFetch('/history/legacy')
}

/**
 * GET /history/legacy/{category}/leads
 * Get leads for a legacy category.
 * @param {string} category
 * @param {{ page?: number, per_page?: number, search?: string, legacy_only?: boolean }} params
 */
export async function getLegacyCategoryLeads(category, params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
  ).toString()
  return apiFetch(`/history/legacy/${encodeURIComponent(category)}/leads${qs ? `?${qs}` : ''}`)
}

/**
 * GET /history/{run_id}
 * Get a single generation run with full details, logs, and statistics.
 * @param {string} runId
 */
export async function getHistoryRun(runId) {
  return apiFetch(`/history/${encodeURIComponent(runId)}`)
}

/**
 * GET /history/{run_id}/leads
 * Get leads that belong to a specific generation run.
 * @param {string} runId
 * @param {{ page?: number, per_page?: number, search?: string }} params
 */
export async function getHistoryRunLeads(runId, params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== ''))
  ).toString()
  return apiFetch(`/history/${encodeURIComponent(runId)}/leads${qs ? `?${qs}` : ''}`)
}

/**
 * DELETE /history/{run_id}
 * Delete a generation run record (does NOT delete the leads).
 * @param {string} runId
 */
export async function deleteHistoryRun(runId) {
  return apiFetch(`/history/${encodeURIComponent(runId)}`, { method: 'DELETE' })
}

/**
 * GET /pdl/health
 * Check whether PDL API key is configured on the backend.
 * @returns {Promise<{ configured: boolean, status: string, message: string }>}
 */
export async function getPDLHealth() {
  return apiFetch('/pdl/health')
}

/**
 * POST /pdl/search-company
 * Find business decision-maker contacts for a company via People Data Labs.
 *
 * @param {{
 *   company_name: string,
 *   domain?:      string | null,
 *   website?:     string | null,
 * }} params
 * @returns {Promise<{
 *   company_name:    string,
 *   company_domain:  string | null,
 *   contacts:        Array<{
 *     name:           string | null,
 *     designation:    string | null,
 *     email:          string | null,
 *     email_type:     string | null,
 *     linkedin_url:   string | null,
 *     company_name:   string | null,
 *     company_domain: string | null,
 *     source:         string,
 *     confidence:     number,
 *   }>,
 *   contacts_found:  number,
 *   emails_found:    number,
 *   pdl_api_calls:   number,
 *   elapsed_seconds: number,
 *   error:           string | null,
 * }>}
 */
export async function searchPDLContacts({ company_name, domain = null, website = null }) {
  return apiFetch('/pdl/search-company', {
    method: 'POST',
    body: JSON.stringify({ company_name, domain: domain || null, website: website || null }),
  })
}

// ── Form Leads (Social Lead Collection) ──────────────────────────────────────

/** POST /form-leads/forms — create a new form */
export async function createForm(payload) {
  return apiFetch('/form-leads/forms', { method: 'POST', body: JSON.stringify(payload) })
}

/** GET /form-leads/forms — list all forms */
export async function listForms(params = {}) {
  const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([,v]) => v != null && v !== ''))).toString()
  return apiFetch(`/form-leads/forms${qs ? `?${qs}` : ''}`)
}

/** GET /form-leads/forms/{form_id} — single form with campaigns */
export async function getFormDetail(formId) {
  return apiFetch(`/form-leads/forms/${encodeURIComponent(formId)}`)
}

/** PUT /form-leads/forms/{form_id} — update form */
export async function updateForm(formId, payload) {
  return apiFetch(`/form-leads/forms/${encodeURIComponent(formId)}`, { method: 'PUT', body: JSON.stringify(payload) })
}

/** DELETE /form-leads/forms/{form_id} — soft-delete form */
export async function deleteForm(formId) {
  return apiFetch(`/form-leads/forms/${encodeURIComponent(formId)}`, { method: 'DELETE' })
}

/** POST /form-leads/forms/{form_id}/campaigns — create a campaign */
export async function createCampaign(formId, payload) {
  return apiFetch(`/form-leads/forms/${encodeURIComponent(formId)}/campaigns`, { method: 'POST', body: JSON.stringify(payload) })
}

/** GET /form-leads/forms/{form_id}/submissions — list submissions */
export async function listSubmissions(formId, params = {}) {
  const qs = new URLSearchParams(Object.fromEntries(Object.entries(params).filter(([,v]) => v != null && v !== ''))).toString()
  return apiFetch(`/form-leads/forms/${encodeURIComponent(formId)}/submissions${qs ? `?${qs}` : ''}`)
}

/** GET /public/forms/{form_id} — fetch public form (no auth) */
export async function getPublicForm(formId) {
  return apiFetch(`/public/forms/${encodeURIComponent(formId)}`)
}

/** POST /public/forms/{form_id}/submit — submit public form */
export async function submitPublicForm(formId, payload) {
  return apiFetch(`/public/forms/${encodeURIComponent(formId)}/submit`, { method: 'POST', body: JSON.stringify(payload) })
}

// ── Social Leads (Phase 2) ────────────────────────────────────────────────────

/**
 * GET /social-leads — list social leads with filters
 */
export async function getSocialLeads(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString()
  return apiFetch(`/social-leads${qs ? `?${qs}` : ''}`)
}

/**
 * GET /social-leads/stats — platform/category/form/campaign counts
 */
export async function getSocialLeadsStats(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString()
  return apiFetch(`/social-leads/stats${qs ? `?${qs}` : ''}`)
}

/**
 * GET /social-leads/{submission_id} — single lead detail
 */
export async function getSocialLead(submissionId) {
  return apiFetch(`/social-leads/${encodeURIComponent(submissionId)}`)
}

/**
 * GET /social-leads/history — grouped submission history for the history panel
 * @param {{ platform?: string, category?: string, form_id?: string, campaign_id?: string }} params
 */
export async function getSocialLeadsHistory(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString()
  return apiFetch(`/social-leads/history${qs ? `?${qs}` : ''}`)
}

/**
 * POST /social-leads/seed-test-data — insert 10 test submissions (dev/test)
 * @param {{ clear_existing?: boolean }} params
 */
export async function seedSocialLeadsTestData(params = {}) {
  return apiFetch('/social-leads/seed-test-data', {
    method: 'POST',
    body: JSON.stringify({ clear_existing: params.clear_existing ?? false }),
  })
}

/**
 * GET /social-leads/export — build the CSV export URL for the given filters.
 * The caller opens/downloads the URL directly (browser handles the file).
 * @param {{ platform?: string, category?: string, form_id?: string, campaign_id?: string, search?: string }} params
 * @returns {string} full URL to trigger the CSV download
 */
export function exportSocialLeads(params = {}) {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== ''))
  ).toString()
  return `${BASE_URL}/social-leads/export${qs ? `?${qs}` : ''}`
}

// ── Lead Status Management ────────────────────────────────────────────────────

/**
 * PATCH /leads/{lead_id}/status
 * Update the status of a single lead (new | interested | not_interested).
 * Pass category so the backend routes to the correct per-category collection.
 *
 * @param {string} leadId
 * @param {'new'|'interested'|'not_interested'} newStatus
 * @param {string|null} category  Industry category (e.g. "Real Estate")
 * @returns {Promise<{ success: boolean, lead: object, status: string, status_updated_at: string }>}
 */
export async function updateLeadStatus(leadId, newStatus, category = null) {
  return apiFetch(`/leads/${encodeURIComponent(leadId)}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status: newStatus, category: category || undefined }),
  })
}

/**
 * GET /leads/status-counts
 * Returns { new: N, interested: N, not_interested: N, total: N } from MongoDB.
 *
 * @param {string|null} category
 * @returns {Promise<{ success: boolean, counts: object }>}
 */
export async function getLeadStatusCounts(category = null) {
  const qs = category ? `?category=${encodeURIComponent(category)}` : ''
  return apiFetch(`/leads/status-counts${qs}`)
}

/**
 * POST /leads/{lead_id}/notes
 * Append a note to an existing lead document.
 *
 * @param {string} leadId
 * @param {string} text
 * @param {string|null} category
 * @returns {Promise<{ success: boolean, note: object, lead: object }>}
 */
export async function addLeadNote(leadId, text, category = null) {
  return apiFetch(`/leads/${encodeURIComponent(leadId)}/notes`, {
    method: 'POST',
    body: JSON.stringify({ text, category: category || undefined }),
  })
}

/**
 * PATCH /leads/{lead_id}/follow-up
 * Set or clear the follow-up date for a lead.
 *
 * @param {string} leadId
 * @param {string|null} followUpDate  ISO date "YYYY-MM-DD" or null to clear
 * @param {string|null} category
 * @returns {Promise<{ success: boolean, follow_up_date: string|null, lead: object }>}
 */
export async function updateLeadFollowUp(leadId, followUpDate, category = null) {
  return apiFetch(`/leads/${encodeURIComponent(leadId)}/follow-up`, {
    method: 'PATCH',
    body: JSON.stringify({ follow_up_date: followUpDate || null, category: category || undefined }),
  })
}

/**
 * GET /leads/follow-ups
 * Returns today's and upcoming follow-up leads.
 *
 * @param {string|null} category
 * @returns {Promise<{ today: object[], upcoming: object[], today_count: number, upcoming_count: number }>}
 */
export async function getFollowUps(category = null) {
  const qs = category ? `?category=${encodeURIComponent(category)}` : ''
  return apiFetch(`/leads/follow-ups${qs}`)
}

// ── Origami Enrichment ────────────────────────────────────────────────────────

/**
 * POST /leads/{lead_id}/enrich-origami
 * Trigger Origami enrichment for a single lead.
 * Falls back gracefully if ORIGAMI_API_KEY is not set.
 *
 * @param {string} leadId
 * @param {string|null} category
 * @returns {Promise<{ success: boolean, lead: object, origami: object, waterfall: object }>}
 */
export async function enrichLeadWithOrigami(leadId, category = null) {
  return apiFetch(`/leads/${encodeURIComponent(leadId)}/enrich-origami`, {
    method: 'POST',
    body: JSON.stringify({ category: category || undefined }),
  })
}

/**
 * POST /leads/bulk-enrich-origami
 * Enrich multiple leads with Origami concurrently.
 *
 * @param {string[]} leadIds
 * @param {string|null} category
 * @param {number} maxConcurrency
 * @returns {Promise<{ success: boolean, total: number, succeeded: number, results: object[] }>}
 */
export async function bulkEnrichOrigami(leadIds, category = null, maxConcurrency = 3) {
  return apiFetch('/leads/bulk-enrich-origami', {
    method: 'POST',
    body: JSON.stringify({
      lead_ids: leadIds,
      category: category || undefined,
      max_concurrency: maxConcurrency,
    }),
  })
}

/**
 * GET /leads/origami-stats
 * Returns real Origami coverage stats calculated from actual database data.
 * Never hardcodes percentages.
 *
 * @param {string|null} category
 * @returns {Promise<{
 *   total_leads: number,
 *   origami_enriched: number,
 *   founder_found: number,
 *   founder_email_found: number,
 *   origami_percent: number,
 *   founder_percent: number,
 *   founder_email_percent: number,
 *   status_breakdown: object,
 * }>}
 */
export async function getOrigamiStats(category = null) {
  const qs = category ? `?category=${encodeURIComponent(category)}` : ''
  return apiFetch(`/leads/origami-stats${qs}`)
}

// ── Origami Standalone Module ─────────────────────────────────────────────────
// These call the isolated /origami/* endpoints (separate from leads pipeline).

/**
 * GET /origami/health
 * Returns configuration status of the standalone Origami module.
 * @returns {Promise<{ configured: boolean, status: string, message: string, base_url: string }>}
 */
export async function getOrigamiHealth() {
  return apiFetch('/origami/health')
}

/**
 * GET /origami/auth-test
 * Live probe to verify ORIGAMI_API_KEY against the real API.
 * @returns {Promise<{ ORIGAMI_AUTHENTICATION: string, ORIGAMI_HTTP_STATUS: number|null, message: string }>}
 */
export async function testOrigamiAuth() {
  return apiFetch('/origami/auth-test')
}

/**
 * POST /origami/search-contacts
 * Find decision-maker contacts for a company via the standalone Origami module.
 *
 * @param {{
 *   company_name: string,
 *   domain?:      string | null,
 *   website?:     string | null,
 *   location?:    string | null,
 *   category?:    string | null,
 * }} params
 * @returns {Promise<{
 *   success:         boolean,
 *   company_name:    string,
 *   contacts:        Array<{
 *     name:         string | null,
 *     title:        string | null,
 *     tier:         number,
 *     tier_label:   string,
 *     email:        string | null,
 *     phone:        string | null,
 *     linkedin_url: string | null,
 *     confidence:   number,
 *   }>,
 *   contacts_found:  number,
 *   emails_found:    number,
 *   phones_found:    number,
 *   founder_status:  string,
 *   elapsed_seconds: number,
 *   error:           string | null,
 * }>}
 */
export async function origamiSearchContacts({ company_name, domain = null, website = null, location = null, category = null }) {
  return apiFetch('/origami/search-contacts', {
    method: 'POST',
    body: JSON.stringify({
      company_name,
      domain:   domain   || undefined,
      website:  website  || undefined,
      location: location || undefined,
      category: category || undefined,
    }),
  })
}

// ── Lead Export ───────────────────────────────────────────────────────────────

/**
 * Build the URL for CSV/Excel export with all current filters applied.
 * The browser navigates to this URL directly so the file downloads natively.
 *
 * @param {'csv'|'excel'} format
 * @param {{ category?, tab?, status?, search?, date_from?, date_to? }} params
 * @returns {string} full URL
 */
export function buildExportUrl(format, params = {}) {
  const endpoint = format === 'excel' ? '/leads/export/excel' : '/leads/export/csv'
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params).filter(([, v]) => v != null && v !== '' && v !== 'all')
    )
  ).toString()
  return `${BASE_URL}${endpoint}${qs ? `?${qs}` : ''}`
}
