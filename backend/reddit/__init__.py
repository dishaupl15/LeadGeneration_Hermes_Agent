"""
reddit/
───────
Standalone Reddit lead-generation module.

Isolation contract
──────────────────
  ✅ This module ONLY imports from:
       reddit/config.py
       reddit/client.py
       reddit/schemas.py
       reddit/search.py
       Standard library + httpx + pydantic + fastapi

  🚫 Does NOT import from:
       app/services/maps_pipeline_service.py
       google_maps/
       people_data_labs/
       contactout/
       prospeo/
       people_enrichment/

  🚫 Does NOT modify the existing Google Maps pipeline.
  🚫 Does NOT scrape Reddit HTML.  Uses Reddit OAuth2 API only.

Endpoints (mounted at /reddit in main.py)
─────────────────────────────────────────
  GET  /reddit/health         — Module health / credentials configured?
  GET  /reddit/auth-test      — Live OAuth2 authentication test
  POST /reddit/search-leads   — Search Reddit and return lead candidates

Removal
───────
  1. Delete backend/reddit/
  2. Remove the two lines in backend/app/main.py:
       from reddit.routes import router as reddit_router
       app.include_router(reddit_router)
  3. Remove the POST /leads/generate-reddit endpoint from
     backend/src/routes/leads.py  (clearly marked with # ── REDDIT section)
  4. Remove the Reddit source selector from the frontend
  The Google Maps pipeline is completely unaffected.
"""
