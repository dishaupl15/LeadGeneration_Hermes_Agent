"""
origami/
────────
Standalone Origami people-enrichment module.

Isolation contract
──────────────────
  ✅ This module ONLY imports from:
       origami/config.py
       origami/client.py
       origami/schemas.py
       origami/people_search.py
       Standard library + httpx + pydantic + fastapi

  🚫 This module does NOT import from:
       app/services/
       src/routes/
       google_maps/
       people_data_labs/
       contactout/
       prospeo/
       people_enrichment/

  🚫 This module does NOT modify the existing pipeline.

Endpoints exposed (mounted at /origami in main.py)
──────────────────────────────────────────────────
  GET  /origami/health          — Module health / key status
  GET  /origami/auth-test       — Live auth test against Origami API
  POST /origami/search-contacts — Find decision-makers for a company

Removal
───────
  To remove this module cleanly:
    1. Delete the origami/ folder.
    2. Remove the two lines in backend/app/main.py:
         from origami.routes import router as origami_router
         app.include_router(origami_router)
    3. Remove the /origami nav link in frontend/src/pages/LeadGeneration.jsx
       and the <Route path="/origami" ...> in frontend/src/App.jsx
    4. Delete frontend/src/pages/OrigamiEnrichment.jsx

  The existing enrichment pipeline (origami_service.py, leads routes) is
  completely unaffected.
"""
