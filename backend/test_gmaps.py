"""
test_gmaps.py — end-to-end test for the Google Maps module.
Run from backend/ directory.
"""
import asyncio
import json
import sys
import httpx

BASE = "http://127.0.0.1:8003"


async def test_health():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/maps-leads/health")
    print(f"\n=== GET /maps-leads/health ===")
    print(f"HTTP {r.status_code}")
    d = r.json()
    print(json.dumps(d, indent=2))
    assert r.status_code == 200
    assert d["api_key_set"] is True
    assert d["status"] == "ready"
    print("PASSED")


async def test_states():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/maps-leads/states")
    print(f"\n=== GET /maps-leads/states ===")
    print(f"HTTP {r.status_code}")
    d = r.json()
    states = d["states"]
    print(f"States returned: {len(states)}")
    print(f"Sample: {states[:5]}")
    assert r.status_code == 200
    assert "Maharashtra" in states
    assert "Karnataka" in states
    assert len(states) >= 20
    print("PASSED")


async def test_districts():
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{BASE}/maps-leads/districts/Maharashtra")
    print(f"\n=== GET /maps-leads/districts/Maharashtra ===")
    print(f"HTTP {r.status_code}")
    d = r.json()
    print(f"State: {d['state']}, Districts: {d['districts']}")
    assert r.status_code == 200
    assert "Pune" in d["districts"]
    assert "Mumbai" in d["districts"]
    print("PASSED")


async def test_generate(label, category, state, district, target, exclude_seen=False):
    body = {
        "category": category,
        "state": state,
        "district": district,
        "target": target,
        "exclude_seen": exclude_seen,
    }
    print(f"\n=== POST /maps-leads/generate — {label} ===")
    print(f"Request: {json.dumps(body, indent=2)}")
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{BASE}/maps-leads/generate", json=body)

    print(f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(f"ERROR: {r.text[:500]}")
        return None

    data = r.json()
    s = data["stats"]

    print(f"\n--- SUMMARY ---")
    print(f"total            : {data['total']}")
    print(f"target           : {data['target']}")
    print(f"target_reached   : {s['target_reached']}")
    print(f"exhausted        : {s['exhausted']}")
    print(f"message          : {data['message']}")
    print(f"api_calls        : {s['total_api_calls']}")
    print(f"raw_results      : {s['total_raw_results']}")
    print(f"duplicates_removed: {s['duplicates_removed']}")
    print(f"secondary_dupes  : {s['secondary_dupes']}")
    print(f"previously_seen  : {s['previously_seen']}")
    print(f"with_phone       : {s['with_phone']}")
    print(f"with_website     : {s['with_website']}")
    print(f"areas_searched   : {s['areas_searched']}")
    print(f"queries_executed : {s['queries_executed']}")
    print(f"elapsed          : {s['elapsed_seconds']}s")

    print(f"\n--- BUSINESSES ({data['total']}) ---")
    # Verify uniqueness
    place_ids = [b["place_id"] for b in data["businesses"]]
    assert len(place_ids) == len(set(place_ids)), "DUPLICATE place_ids in response!"

    for i, b in enumerate(data["businesses"], 1):
        print(f"[{i:>3}] {b['name']}")
        print(f"       place_id : {b['place_id']}")
        print(f"       address  : {b['address']}")
        print(f"       phone    : {b['phone']}")
        print(f"       website  : {b['website']}")
        print(f"       type     : {b['primary_type']}")
        print(f"       source   : {b['source']}")
        # Verify source field
        assert b["source"] == "google_maps", f"wrong source: {b['source']}"
        # Every business must have a name and place_id
        assert b["name"], "empty name"
        assert b["place_id"], "empty place_id"

    print(f"\nUniqueness check: {len(place_ids)} unique place_ids — PASSED")
    print("PASSED")
    return data


async def main():
    print("=" * 60)
    print("Google Maps Module — End-to-End Tests")
    print("=" * 60)

    await test_health()
    await test_states()
    await test_districts()

    # Test 1: target=10, specific district
    data1 = await test_generate(
        label="target=10, construction, Maharashtra, Pune",
        category="construction",
        state="Maharashtra",
        district="Pune",
        target=10,
        exclude_seen=False,
    )

    # Test 2: target=50, state-wide (no district)
    data2 = await test_generate(
        label="target=50, construction, Maharashtra (state-wide)",
        category="construction",
        state="Maharashtra",
        district=None,
        target=50,
        exclude_seen=False,
    )

    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    if data1:
        s1 = data1["stats"]
        print(f"\nTest 1 (target=10, Pune):")
        print(f"  Returned   : {data1['total']}/{data1['target']}")
        print(f"  API calls  : {s1['total_api_calls']}")
        print(f"  Raw results: {s1['total_raw_results']}")
        print(f"  Dupes removed: {s1['duplicates_removed'] + s1['secondary_dupes']}")
        print(f"  With phone : {s1['with_phone']}")
        print(f"  With website: {s1['with_website']}")
        print(f"  Elapsed    : {s1['elapsed_seconds']}s")
    if data2:
        s2 = data2["stats"]
        print(f"\nTest 2 (target=50, Maharashtra state-wide):")
        print(f"  Returned   : {data2['total']}/{data2['target']}")
        print(f"  API calls  : {s2['total_api_calls']}")
        print(f"  Raw results: {s2['total_raw_results']}")
        print(f"  Dupes removed: {s2['duplicates_removed'] + s2['secondary_dupes']}")
        print(f"  With phone : {s2['with_phone']}")
        print(f"  With website: {s2['with_website']}")
        print(f"  Elapsed    : {s2['elapsed_seconds']}s")


asyncio.run(main())
