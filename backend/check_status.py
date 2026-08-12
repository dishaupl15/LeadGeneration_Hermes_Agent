cs = open("app/services/companyenrich_service.py", encoding="utf-8").read()
es = open("app/services/enrichment_service.py", encoding="utf-8").read()
ds = open("app/services/discovery_service.py", encoding="utf-8").read()
rs = open("src/routes/leads.py", encoding="utf-8").read()

def ok(label, val):
    print(("OK  " if val else "NEED"), label)

ok("CE reset_credits_flag", "def reset_credits_flag" in cs)
ok("CE _mark_exhausted x4", cs.count("_mark_exhausted()") >= 4)
ok("CE search_companies early-exit", "_credits_exhausted" in cs[cs.find("def search_companies"):cs.find("def search_companies")+200])
ok("CE enrich_by_domain early-exit", "_credits_exhausted" in cs[cs.find("async def enrich_company_by_domain"):cs.find("async def enrich_company_by_domain")+200])
ok("CE get_person_email early-exit", "_credits_exhausted" in cs[cs.find("async def get_person_email"):cs.find("async def get_person_email")+200])
hb = es[es.find("hard_required"):es.find("hard_required")+300]
ok("ES email HARD", "email" in hb and "company_number" in hb)
ok("ES address NOT hard", "address" not in hb)
ok("ES is_credits_exhausted", "is_credits_exhausted" in es)
gp = ds[ds.find("geo_passes"):ds.find("geo_passes")+200] if "geo_passes" in ds else ""
ok("DS geo_passes Pune-free", "pune" not in gp.lower() or not gp)
ok("DS reset_credits_flag", "reset_credits_flag" in ds)
ok("DS Pune hard filter gone", "does not satisfy Pune requirement" not in ds)
ok("DS has_pune hard gone", "no Pune/Pimpri/Hinjewadi relevance" not in ds)
validate_block = ds[ds.find("def validate_candidate"):ds.find("def validate_candidate")+150]
ok("DS validate no geo_expansion param", "geo_expansion" not in validate_block)
dl_block = ds[ds.find("async def discover_leads"):ds.find("async def discover_leads")+600]
ok("DS discover_leads India-wide doc", "India-wide" in dl_block or "india" in dl_block.lower())
ok("DS MIN_COMPANIES=5", "MIN_COMPANIES = 5" in ds)
mn = ds.find("MIN_COMPANIES")
ok("DS email+phone final gate in discover_leads", "email" in ds[mn:mn+3000] and "company_number" in ds[mn:mn+3000])
ok("RS reset_credits_flag", "reset_credits_flag" in rs)
ok("RS CE status logged", "DISABLED_402" in rs or "AVAILABLE" in rs)
