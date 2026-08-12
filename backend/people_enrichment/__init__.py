"""
people_enrichment/
──────────────────
Orchestration layer that calls PDL → Prospeo → ContactOut in a waterfall.

The three provider modules remain completely independent:
  backend/people_data_labs/   ← untouched
  backend/prospeo/            ← untouched
  backend/contactout/         ← untouched

This package ONLY contains the orchestration logic.

Public API:
  from people_enrichment.orchestrator import enrich_company_contacts, reset_cache
  from people_enrichment.schemas import PeopleEnrichmentResult, EnrichedContact, ProviderStats
  from people_enrichment.dedup import dedup_and_merge, count_useful
  from people_enrichment.scoring import rank_contacts, is_useful
"""
