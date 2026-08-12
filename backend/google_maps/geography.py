"""
google_maps/geography.py
─────────────────────────
Static geographic subdivision data for India.

Structure
─────────
  INDIA_GEO: dict[state_name, dict[district_name, list[locality]]]

Used by discovery.py to build search area lists:
  • State-level  → all districts in that state
  • District-level → localities within that district

Localities are smaller searchable areas within each district.  They give
the Places API a tighter bounding context so more unique results are returned
across multiple calls (avoiding the ~60-result cap per query).

Coverage: all 28 states + 8 UTs of India.  Populated with major districts
and representative localities; can be extended by adding to any list.
"""
from __future__ import annotations

# Format:
#   state → {district: [locality, …], …}
#
# Localities follow the convention used by Google Maps  — typically the
# municipal area or well-known neighborhood name.

INDIA_GEO: dict[str, dict[str, list[str]]] = {
    # ── Maharashtra ───────────────────────────────────────────────────────────
    "Maharashtra": {
        "Pune": [
            "Shivajinagar", "Kothrud", "Hadapsar", "Baner", "Wakad",
            "Hinjewadi", "Kharadi", "Viman Nagar", "Koregaon Park", "Aundh",
            "Pimpri", "Chinchwad", "Nigdi", "Bavdhan", "Magarpatta",
            "Deccan", "Swargate", "Kalyani Nagar", "Wagholi", "Undri",
        ],
        "Mumbai": [
            "Andheri", "Bandra", "Dadar", "Borivali", "Powai", "Malad",
            "Goregaon", "Thane", "Kurla", "Vikhroli", "Santacruz",
            "Worli", "Lower Parel", "BKC", "Nariman Point", "Colaba",
            "Kandivali", "Mulund", "Ghatkopar", "Chembur",
        ],
        "Nashik": [
            "Nashik Road", "Satpur", "Ambad", "Cidco", "Panchavati",
            "Gangapur Road", "Deolali", "Malegaon",
        ],
        "Nagpur": [
            "Sitabuldi", "Dharampeth", "Gandhibagh", "MIDC Nagpur",
            "Hingna", "Butibori", "Kamptee", "Koradi",
        ],
        "Aurangabad": [
            "Waluj MIDC", "Chikalthana", "Cidco Aurangabad",
            "Garkheda", "Bajajnagar",
        ],
        "Kolhapur": [
            "Kolhapur City", "Kagal", "Ichalkaranji", "Hatkanangale",
        ],
        "Solapur": [
            "Solapur City", "Akkalkot", "Pandharpur",
        ],
        "Amravati": [
            "Amravati City", "Achalpur", "Daryapur",
        ],
        "Navi Mumbai": [
            "Vashi", "Airoli", "Belapur", "Nerul", "Kharghar",
            "Panvel", "Kalamboli", "Ulwe",
        ],
        "Thane": [
            "Thane City", "Kalyan", "Dombivli", "Bhiwandi",
            "Ulhasnagar", "Badlapur", "Ambarnath",
        ],
    },
    # ── Karnataka ─────────────────────────────────────────────────────────────
    "Karnataka": {
        "Bengaluru Urban": [
            "Koramangala", "Indiranagar", "Whitefield", "Electronic City",
            "HSR Layout", "Marathahalli", "Jayanagar", "BTM Layout",
            "Bannerghatta Road", "Outer Ring Road", "Yelahanka",
            "Hebbal", "Rajajinagar", "Malleshwaram", "Yeshwanthpur",
            "Bellandur", "Sarjapur Road", "Domlur", "Silk Board",
        ],
        "Mysuru": [
            "Mysore City", "Hebbal Mysore", "Nanjangud",
        ],
        "Hubli-Dharwad": [
            "Hubli", "Dharwad",
        ],
        "Mangaluru": [
            "Mangalore City", "Ullal", "Bajpe",
        ],
        "Belagavi": [
            "Belagavi City", "Gokak", "Nipani",
        ],
        "Tumakuru": [
            "Tumkur City", "Sira", "Madhugiri",
        ],
    },
    # ── Tamil Nadu ────────────────────────────────────────────────────────────
    "Tamil Nadu": {
        "Chennai": [
            "Anna Nagar", "T Nagar", "Adyar", "Velachery", "Porur",
            "Perungudi", "Sholinganallur", "OMR", "Guindy", "Nungambakkam",
            "Kilpauk", "Mylapore", "Egmore", "Ambattur", "Ambattur SIDCO",
            "Poonamallee", "Saidapet", "Chromepet",
        ],
        "Coimbatore": [
            "RS Puram", "Peelamedu", "Saibaba Colony", "Gandhipuram",
            "SIDCO Coimbatore", "Singanallur",
        ],
        "Madurai": [
            "Madurai City", "Anna Nagar Madurai", "Alagarkoil Road",
        ],
        "Tiruchirappalli": [
            "Trichy City", "Thillainagar", "Woraiyur",
        ],
        "Salem": [
            "Salem City", "Suramangalam", "Hasthampatti",
        ],
        "Tirunelveli": [
            "Tirunelveli City", "Palayamkottai",
        ],
        "Vellore": [
            "Vellore City", "Katpadi",
        ],
    },
    # ── Telangana ─────────────────────────────────────────────────────────────
    "Telangana": {
        "Hyderabad": [
            "Banjara Hills", "Jubilee Hills", "Gachibowli", "Madhapur",
            "HITEC City", "Kukatpally", "Begumpet", "Secunderabad",
            "Ameerpet", "Somajiguda", "Miyapur", "Kondapur",
            "Manikonda", "Nanakramguda", "Financial District",
        ],
        "Rangareddy": [
            "LB Nagar", "Dilsukhnagar", "Uppal", "Mehdipatnam",
        ],
        "Medchal-Malkajgiri": [
            "Kompally", "Alwal", "Bowenpally", "Medchal",
        ],
        "Warangal Urban": [
            "Warangal City", "Hanamkonda", "Kazipet",
        ],
        "Karimnagar": [
            "Karimnagar City", "Peddapalli",
        ],
        "Nizamabad": [
            "Nizamabad City",
        ],
    },
    # ── Gujarat ───────────────────────────────────────────────────────────────
    "Gujarat": {
        "Ahmedabad": [
            "SG Road", "CG Road", "Navrangpura", "Satellite", "Prahlad Nagar",
            "Bopal", "Bodakdev", "Vastrapur", "Maninagar", "Naranpura",
            "Chandkheda", "Gota", "Thaltej", "Ranip",
        ],
        "Surat": [
            "Ring Road Surat", "Adajan", "Vesu", "Katargam", "Udhna",
            "Sachin GIDC", "Surat Diamond Bourse",
        ],
        "Vadodara": [
            "Vadodara City", "Alembic Road", "Makarpura GIDC", "Akota",
        ],
        "Rajkot": [
            "Rajkot City", "150 Ft Ring Road", "Kalawad Road",
        ],
        "Gandhinagar": [
            "Gandhinagar Sector", "Gift City",
        ],
        "Anand": [
            "Anand City", "Vallabh Vidyanagar",
        ],
        "Bharuch": [
            "Bharuch City", "Ankleshwar GIDC",
        ],
    },
    # ── Delhi NCR ─────────────────────────────────────────────────────────────
    "Delhi": {
        "New Delhi": [
            "Connaught Place", "Nehru Place", "Janakpuri", "Dwarka",
            "Rohini", "Pitampura", "Saket", "Vasant Kunj", "Okhla",
            "Lajpat Nagar", "Karol Bagh", "Patel Nagar", "Rajouri Garden",
        ],
        "North West Delhi": [
            "Shalimar Bagh", "Model Town", "Ashok Vihar",
        ],
        "South West Delhi": [
            "Dwarka Sector", "Uttam Nagar",
        ],
    },
    # ── Haryana ───────────────────────────────────────────────────────────────
    "Haryana": {
        "Gurugram": [
            "DLF Cyber City", "Sector 29", "Sector 44", "MG Road Gurugram",
            "Sohna Road", "Golf Course Road", "Udyog Vihar",
            "NH-48 Gurugram", "Manesar", "Sector 56",
        ],
        "Faridabad": [
            "Faridabad City", "NIT Faridabad", "Sector 37 Faridabad",
        ],
        "Ambala": [
            "Ambala City", "Ambala Cantonment",
        ],
        "Hisar": [
            "Hisar City",
        ],
        "Rohtak": [
            "Rohtak City",
        ],
    },
    # ── Uttar Pradesh ─────────────────────────────────────────────────────────
    "Uttar Pradesh": {
        "Gautam Buddh Nagar": [
            "Noida Sector 62", "Noida Sector 18", "Noida Sector 16",
            "Greater Noida", "Knowledge Park", "Techzone",
            "Noida Expressway",
        ],
        "Ghaziabad": [
            "Vaishali", "Kaushambi", "Raj Nagar Extension",
            "Indirapuram", "Loni", "Modinagar",
        ],
        "Lucknow": [
            "Hazratganj", "Gomti Nagar", "Aliganj", "Vikas Nagar",
            "Indira Nagar Lucknow", "Chinhat",
        ],
        "Kanpur Nagar": [
            "Kanpur City", "Civil Lines Kanpur", "Kidwai Nagar",
        ],
        "Agra": [
            "Agra City", "Fatehabad Road", "Sikandara",
        ],
        "Varanasi": [
            "Varanasi City", "Lanka Varanasi", "Sarnath",
        ],
        "Meerut": [
            "Meerut City", "Shastri Nagar Meerut",
        ],
    },
    # ── Rajasthan ─────────────────────────────────────────────────────────────
    "Rajasthan": {
        "Jaipur": [
            "Malviya Nagar Jaipur", "C-Scheme", "Vaishali Nagar Jaipur",
            "Mansarovar", "Jagatpura", "Sanganer", "Sitapura Industrial",
        ],
        "Jodhpur": [
            "Jodhpur City", "Ratanada", "Shastri Nagar Jodhpur",
        ],
        "Udaipur": [
            "Udaipur City", "Hiran Magri",
        ],
        "Kota": [
            "Kota City", "Talwandi",
        ],
        "Ajmer": [
            "Ajmer City", "Pushkar",
        ],
    },
    # ── Madhya Pradesh ────────────────────────────────────────────────────────
    "Madhya Pradesh": {
        "Indore": [
            "Vijay Nagar Indore", "Palasia", "AB Road Indore",
            "Nipania", "Scheme 54", "Bhawarkuan",
        ],
        "Bhopal": [
            "MP Nagar", "Arera Colony", "Hoshangabad Road", "New Market Bhopal",
        ],
        "Gwalior": [
            "Lashkar", "Morar", "City Centre Gwalior",
        ],
        "Jabalpur": [
            "Napier Town", "Civil Lines Jabalpur",
        ],
    },
    # ── West Bengal ───────────────────────────────────────────────────────────
    "West Bengal": {
        "Kolkata": [
            "Park Street", "Salt Lake Sector V", "Rajarhat Newtown",
            "Dum Dum", "Howrah", "Jadavpur", "Behala",
            "Ballygunge", "Alipore", "Esplanade",
        ],
        "Howrah": [
            "Howrah City", "Liluah", "Shibpur",
        ],
        "North 24 Parganas": [
            "Barasat", "Madhyamgram",
        ],
    },
    # ── Kerala ────────────────────────────────────────────────────────────────
    "Kerala": {
        "Ernakulam": [
            "Kakkanad", "Palarivattom", "Edapally", "MG Road Kochi",
            "Thrippunithura", "Perumbavoor",
        ],
        "Thiruvananthapuram": [
            "Technopark", "Pattom", "Kowdiar", "Kazhakkoottam",
        ],
        "Kozhikode": [
            "Kozhikode City", "Cyber Park Kozhikode",
        ],
        "Thrissur": [
            "Thrissur City", "Ollur",
        ],
        "Palakkad": [
            "Palakkad City", "Coimbatore Road Palakkad",
        ],
    },
    # ── Andhra Pradesh ────────────────────────────────────────────────────────
    "Andhra Pradesh": {
        "Visakhapatnam": [
            "MVP Colony", "Gajuwaka", "Steel Plant Area",
            "BHPV", "Rushikonda",
        ],
        "Krishna": [
            "Vijayawada", "Auto Nagar Vijayawada", "Benz Circle",
        ],
        "Guntur": [
            "Guntur City", "Brodipet",
        ],
        "Nellore": [
            "Nellore City", "Vedayapalem",
        ],
        "Chittoor": [
            "Tirupati", "Srikalahasti",
        ],
    },
    # ── Punjab ────────────────────────────────────────────────────────────────
    "Punjab": {
        "Ludhiana": [
            "Ludhiana City", "Focal Point", "Ferozepur Road Ludhiana",
            "BRS Nagar",
        ],
        "Amritsar": [
            "Amritsar City", "Hall Bazaar", "Ranjit Avenue",
        ],
        "Jalandhar": [
            "Jalandhar City", "Model Town Jalandhar",
        ],
        "Mohali": [
            "Phase 8", "Phase 9", "IT Park Mohali", "Sector 70 Mohali",
        ],
    },
    # ── Odisha ────────────────────────────────────────────────────────────────
    "Odisha": {
        "Khordha": [
            "Bhubaneswar", "Infocity Bhubaneswar", "Patia", "Nayapalli",
        ],
        "Cuttack": [
            "Cuttack City", "Badambadi",
        ],
        "Sundargarh": [
            "Rourkela",
        ],
    },
    # ── Bihar ─────────────────────────────────────────────────────────────────
    "Bihar": {
        "Patna": [
            "Patna City", "Boring Road", "Kankar Bagh", "Bailey Road",
        ],
        "Gaya": [
            "Gaya City",
        ],
        "Muzaffarpur": [
            "Muzaffarpur City",
        ],
    },
    # ── Jharkhand ─────────────────────────────────────────────────────────────
    "Jharkhand": {
        "Ranchi": [
            "Ranchi City", "Lalpur", "Doranda",
        ],
        "East Singhbhum": [
            "Jamshedpur", "Adityapur",
        ],
    },
    # ── Uttarakhand ───────────────────────────────────────────────────────────
    "Uttarakhand": {
        "Dehradun": [
            "Rajpur Road", "Ballupur", "Prem Nagar Dehradun",
        ],
        "Haridwar": [
            "SIDCUL Haridwar", "Roorkee",
        ],
    },
    # ── Himachal Pradesh ──────────────────────────────────────────────────────
    "Himachal Pradesh": {
        "Shimla": [
            "Shimla City", "Lakkar Bazaar",
        ],
        "Kangra": [
            "Dharamsala", "Palampur",
        ],
    },
    # ── Chandigarh (UT) ───────────────────────────────────────────────────────
    "Chandigarh": {
        "Chandigarh": [
            "Sector 17", "Sector 35", "IT Park Chandigarh",
            "Industrial Area Phase 1", "Industrial Area Phase 2",
        ],
    },
    # ── Goa ───────────────────────────────────────────────────────────────────
    "Goa": {
        "North Goa": [
            "Panaji", "Mapusa", "Calangute", "Candolim",
        ],
        "South Goa": [
            "Margao", "Vasco", "Colva",
        ],
    },
    # ── Assam ─────────────────────────────────────────────────────────────────
    "Assam": {
        "Kamrup Metropolitan": [
            "Guwahati", "Dispur", "Panbazar",
        ],
        "Dibrugarh": [
            "Dibrugarh City",
        ],
    },
    # ── Chhattisgarh ──────────────────────────────────────────────────────────
    "Chhattisgarh": {
        "Raipur": [
            "Raipur City", "Pandri", "Shankar Nagar Raipur",
        ],
        "Durg": [
            "Bhilai",
        ],
    },
}


# ── Helper functions ──────────────────────────────────────────────────────────

def get_all_states() -> list[str]:
    """Return sorted list of all state names."""
    return sorted(INDIA_GEO.keys())


def get_districts(state: str) -> list[str]:
    """Return all district names for a given state (case-insensitive match)."""
    for s, districts in INDIA_GEO.items():
        if s.lower() == state.lower():
            return sorted(districts.keys())
    return []


def get_localities(state: str, district: str) -> list[str]:
    """Return all localities for a given state + district."""
    for s, districts in INDIA_GEO.items():
        if s.lower() == state.lower():
            for d, locs in districts.items():
                if d.lower() == district.lower():
                    return locs
            return []
    return []


def resolve_areas(state: str, district: str) -> list[str]:
    """
    Return the list of search areas to iterate for this state/district.

    Logic:
    - If district is specified and has localities → return localities
    - If district is specified but no localities   → return [district]
    - If only state is specified                   → return all districts
    """
    if state and district:
        locs = get_localities(state, district)
        if locs:
            return locs
        # District exists in the state?
        districts = get_districts(state)
        if district in districts or district.lower() in [d.lower() for d in districts]:
            return [district]
        # Fallback: treat district as a plain area name
        return [district]
    if state:
        districts = get_districts(state)
        return districts if districts else [state]
    return []
