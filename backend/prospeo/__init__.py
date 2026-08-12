"""
prospeo/
────────
Standalone Prospeo people-enrichment module.

Workflow:
  company name + domain
    → Search Person (/search-person)
    → collect person_ids of relevant decision-makers
    → Bulk Enrich Person (/bulk-enrich-person)
    → extract email + mobile
    → return normalised contacts

Completely isolated: does NOT import from google_maps/, people_data_labs/,
app/services/, or src/.  Can be wired to any orchestrator independently.
"""
