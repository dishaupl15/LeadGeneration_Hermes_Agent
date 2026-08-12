"""
people_data_labs/
─────────────────
Isolated People Data Labs contact discovery module.

Discovers business decision-makers (founders, HR, directors, etc.)
for a given company using the PDL Person Search API.

This module is COMPLETELY ISOLATED from:
  - google_maps/
  - app/services/companyenrich_service.py
  - app/services/discovery_service.py
  - app/services/maps_pipeline_service.py
  - src/routes/leads.py

Entry points:
  from people_data_labs.people_search import search_company_contacts
  from people_data_labs.routes import router

API mounted at /pdl/ in app/main.py.
"""
