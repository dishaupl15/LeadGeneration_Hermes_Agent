"""
google_maps/
────────────
Completely isolated Google Maps / Google Places lead-generation module.

This package DOES NOT import from or modify:
  - app/services/  (discovery, enrichment, hermes, companyenrich, …)
  - src/routes/leads.py
  - tools/leadgen.py
  - Any existing pipeline code

It exposes its own FastAPI router at /maps-leads/ that app/main.py mounts
alongside the existing /leads/ router without any coupling.

Public surface
──────────────
  google_maps.routes.router   — FastAPI APIRouter to include in main.py
"""
