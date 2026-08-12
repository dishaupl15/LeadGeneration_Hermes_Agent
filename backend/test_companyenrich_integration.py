import httpx
import unittest
from unittest.mock import AsyncMock, patch

from app.services import companyenrich_service, discovery_service, enrichment_service
from src.schemas.lead_schema import GenerateLeadsRequest


class CompanyEnrichIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        enrichment_service._DOMAIN_CACHE.clear()

    async def test_enrich_one_uses_companyenrich_when_fields_missing(self):
        company = {
            "company_name": "Acme Labs",
            "domain": "acmelabs.com",
            "city": "Pune",
            "state": "Maharashtra",
            "country": "India",
            "email": None,
            "company_number": None,
            "address": None,
            "founder_name": None,
            "_field_verification": {},
        }

        companyenrich_details = {
            "email": "hello@acmelabs.com",
            "company_number": "+91 9876543210",
            "address": "Pune, Maharashtra, India",
            "founder_name": "Amit Patel",
            "city": "Pune",
            "state": "Maharashtra",
            "country": "India",
        }

        with patch(
            "app.services.enrichment_service._companyenrich_key",
            new=lambda: "fake-key",
        ), patch(
            "app.services.companyenrich_service.find_company_details",
            new=AsyncMock(return_value=companyenrich_details),
        ), patch(
            "app.services.companyenrich_service.search_people",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.companyenrich_service.get_person_email",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.enrichment_service._hunter_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._apollo_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._pdl_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._gplaces_key",
            new=lambda: "",
        ):
            updated = await enrichment_service._enrich_one(company, requested_city="Pune")

        self.assertEqual(updated["email"], "hello@acmelabs.com")
        self.assertEqual(updated["company_number"], "+91 9876543210")
        self.assertEqual(updated["address"], "Pune, Maharashtra, India")
        self.assertEqual(updated["founder_name"], "Amit Patel")
        self.assertEqual(updated["city"], "Pune")


    async def test_enrich_one_uses_companyenrich_people_email_lookup(self):
        company = {
            "company_name": "Acme Labs",
            "domain": "acmelabs.com",
            "city": "Pune",
            "state": "Maharashtra",
            "country": "India",
            "email": None,
            "company_number": None,
            "address": "Pune, Maharashtra, India",
            "founder_name": None,
            "_field_verification": {},
        }

        with patch(
            "app.services.enrichment_service._companyenrich_key",
            new=lambda: "fake-key",
        ), patch(
            "app.services.enrichment_service._hunter_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._apollo_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._pdl_key",
            new=lambda: "",
        ), patch(
            "app.services.enrichment_service._gplaces_key",
            new=lambda: "",
        ), patch(
            "app.services.companyenrich_service.find_company_details",
            new=AsyncMock(return_value={
                "company_number": "+91 9876543210",
                "address": "Pune, Maharashtra, India",
            }),
        ), patch(
            "app.services.companyenrich_service.search_people",
            new=AsyncMock(return_value=[{
                "id": 123,
                "name": "Amit Patel",
                "position": "Founder",
                "seniority": "Founder",
            }]),
        ), patch(
            "app.services.companyenrich_service.get_person_email",
            new=AsyncMock(return_value={
                "status": "found",
                "email": "amit.patel@acmelabs.com",
            }),
        ):
            updated = await enrichment_service._enrich_one(company, requested_city="Pune")

        self.assertEqual(updated["email"], "amit.patel@acmelabs.com")
        self.assertEqual(updated["company_number"], "+91 9876543210")
        self.assertEqual(updated["address"], "Pune, Maharashtra, India")
        self.assertEqual(updated["founder_name"], "Amit Patel")
        self.assertEqual(updated["city"], "Pune")


    async def test_discover_candidates_uses_companyenrich_search_first(self):
        with patch(
            "app.services.companyenrich_service.search_companies",
            new=AsyncMock(return_value=[{
                "id": "1",
                "name": "Acme Real Estate",
                "domain": "acme-realestate.com",
                "website": "https://acme-realestate.com",
                "description": "Real estate company in Pune",
            }]),
        ):
            candidates = await discovery_service.discover_candidates("Real Estate in Pune", 1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "companyenrich")
        self.assertEqual(candidates[0]["domain"], "acme-realestate.com")


    async def test_pharma_candidate_rejects_irrelevant_hotel_spa_company(self):
        company = {
            "company_name": "Pune Spa Retreat",
            "domain": "punesparetreat.com",
            "_merged_markdown": "Luxury hotel and spa services for guests in Pune",
        }
        ok, reason = discovery_service.validate_candidate(company, "Pharma in Pune")

        self.assertFalse(ok)
        self.assertIn("pharma candidate contains irrelevant term", reason)


    async def test_find_company_details_rejects_mismatched_domain_details(self):
        class DummyClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def get(self, *args, **kwargs):
                return httpx.Response(200, json={"domain": "wrongdomain.com"})
            async def post(self, *args, **kwargs):
                return httpx.Response(200, json={"domain": "wrongdomain.com"})

        with patch(
            "app.services.companyenrich_service._get_client",
            new=lambda: DummyClient(),
        ), patch(
            "app.services.companyenrich_service.search_companies",
            new=AsyncMock(return_value=[{"domain": "wrongdomain.com"}]),
        ):
            details = await companyenrich_service.find_company_details(
                "Acme Labs",
                "acmelabs.com",
            )

        self.assertIsNone(details)

    async def test_find_company_details_rejects_mismatched_company_name(self):
        class DummyClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc, tb):
                return False
            async def get(self, *args, **kwargs):
                return httpx.Response(200, json={"domain": "acmelabs.com", "company_name": "Wrong Company"})
            async def post(self, *args, **kwargs):
                return httpx.Response(200, json={"domain": "acmelabs.com", "company_name": "Wrong Company"})

        with patch(
            "app.services.companyenrich_service._get_client",
            new=lambda: DummyClient(),
        ), patch(
            "app.services.companyenrich_service.search_companies",
            new=AsyncMock(return_value=[{"domain": "acmelabs.com", "company_name": "Wrong Company"}]),
        ):
            details = await companyenrich_service.find_company_details(
                "Acme Labs",
                "acmelabs.com",
            )

        self.assertIsNone(details)


    async def test_discover_candidates_falls_back_to_serper_when_companyenrich_empty(self):
        with patch(
            "app.services.companyenrich_service.search_companies",
            new=AsyncMock(return_value=[]),
        ), patch(
            "app.services.discovery_service._serper_search",
            new=AsyncMock(return_value=[{
                "title": "Fallback Realty",
                "link": "https://fallback-realty.com",
                "domain": "fallback-realty.com",
                "snippet": "Fallback company result",
                "source": "organic",
            }]),
        ):
            candidates = await discovery_service.discover_candidates("Real Estate in Pune", 1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "organic")
        self.assertEqual(candidates[0]["domain"], "fallback-realty.com")

    async def test_resolved_query_ignores_legacy_city_for_india_search(self):
        payload = GenerateLeadsRequest(industry="Pharma", city="Pune", count=10)
        self.assertEqual(payload.resolved_query(), "Pharma")

    async def test_validate_candidate_rejects_lasik_in_pune_for_pharma(self):
        company = {
            "company_name": "Lasik in Pune",
            "domain": "lasikinpune.com",
            "_merged_markdown": "Lasik eye surgery clinic in Pune offering vision correction and laser eye care.",
            "description": "Eye surgery clinic and lens care center.",
        }
        ok, reason = discovery_service.validate_candidate(company, "Pharma")
        self.assertFalse(ok)
        self.assertIn("pharma candidate contains irrelevant term", reason)


if __name__ == "__main__":
    unittest.main()
