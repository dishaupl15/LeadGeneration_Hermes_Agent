"""
contactout/
────────────
Standalone ContactOut people-enrichment module.

Workflow:
  company name + domain
    → POST /v1/people/search  (company + domain + job_titles + reveal_info=true)
    → extract contact_info.emails / contact_info.phones
    → rank by role priority
    → return up to CONTACTOUT_MAX_CONTACTS_PER_COMPANY normalised contacts

Completely isolated: does NOT import from google_maps/, people_data_labs/,
prospeo/, app/services/, or src/.
"""
