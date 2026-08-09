#!/usr/bin/env python3
"""Crawl company websites for contact info: emails, phones, address."""
import re, sys, json
from urllib.request import Request, urlopen
from urllib.error import URLError

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def fetch(url, timeout=15):
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"<error>{e}</error>"

def extract_emails(html):
    return sorted(set(re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", html)))

def extract_phones(html):
    # Indian phone patterns
    patterns = [
        r"\+91[\s-]?\d{10}",
        r"\+91[\s-]?\d{4}[\s-]?\d{3}[\s-]?\d{3}",
        r"0\d{2,4}[\s-]?\d{3}[\s-]?\d{4}",
        r"\b\d{10}\b",
        r"\b\d{3,4}[\s-]?\d{3}[\s-]?\d{4}\b",
    ]
    phones = set()
    for p in patterns:
        for m in re.findall(p, html):
            phones.add(m.strip())
    return sorted(phones)[:5]

def extract_address(html):
    # Try to find address-like text near "contact" or "address"
    lines = html.split("\n")
    addr_lines = []
    in_addr = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.search(r"(contact|address|head.?quarter|registered.?office)", stripped, re.I):
            # grab next 5 non-empty lines
            collected = []
            for j in range(i, min(i+6, len(lines))):
                t = lines[j].strip()
                if t and len(t) > 10:
                    # clean HTML tags
                    t = re.sub(r"<[^>]+>", "", t)
                    t = re.sub(r"\s+", " ", t).strip()
                    if t and len(t) > 8:
                        collected.append(t)
            if collected:
                return " | ".join(collected[:3])
    return ""

def crawl(name, url, contact_paths):
    result = {
        "company_name": name,
        "website": url,
        "emails": [],
        "phones": [],
        "address": {"street": "", "city": "", "state": "", "country": "", "postal_code": ""},
        "sources": []
    }
    
    # Fetch homepage
    homepage = fetch(url)
    result["sources"].append(url)
    
    # Try contact pages
    for path in contact_paths:
        full_url = url.rstrip("/") + path
        html = fetch(full_url)
        result["sources"].append(full_url)
        if "<error>" in html:
            continue
        
        emails = extract_emails(html)
        phones = extract_phones(html)
        addr = extract_address(html)
        
        # Filter out common non-contact emails
        filtered_emails = [e for e in emails if not any(
            x in e.lower() for x in ["example.com", "domain.com", "test.com", "yourdomain", "w3.org", "schema.org"]
        )]
        
        if filtered_emails:
            result["emails"] = filtered_emails
        if phones:
            result["phones"] = phones
        if addr:
            result["address"]["street"] = addr[:200]
        
        if filtered_emails or phones:
            break  # Found contact info, stop
    
    # Also try homepage for common patterns
    if not result["emails"]:
        emails = extract_emails(homepage)
        filtered = [e for e in emails if not any(
            x in e.lower() for x in ["example.com", "domain.com", "test.com", "w3.org", "schema.org"]
        )]
        if filtered:
            result["emails"] = filtered[:5]
    
    if not result["phones"]:
        phones = extract_phones(homepage)
        if phones:
            result["phones"] = phones[:3]
    
    return result


if __name__ == "__main__":
    companies = [
        {
            "name": "Sai Prasad Corporation",
            "url": "https://www.saiprasadgroup.com",
            "contact_paths": ["/contact-us", "/contact", "/contactus"]
        },
        {
            "name": "DSK Group",
            "url": "http://www.dskgroup.co.in",
            "contact_paths": ["/contact-us", "/contact", "/contactus", "/contact.aspx"]
        },
        {
            "name": "Godrej Properties",
            "url": "https://www.godrejproperties.com",
            "contact_paths": ["/contact-us", "/contact", "/contactus", "/reach-us"]
        }
    ]
    
    results = []
    for c in companies:
        print(f"Crawling {c['name']}...", file=sys.stderr)
        r = crawl(c["name"], c["url"], c["contact_paths"])
        results.append(r)
        print(f"  emails={r['emails']}, phones={r['phones']}", file=sys.stderr)
    
    output = {
        "query": "Real estate companies in Pune",
        "timestamp": "",
        "companies": results
    }
    print(json.dumps(output, indent=2))