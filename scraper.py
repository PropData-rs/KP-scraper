"""
KupujemProdajem – Real Estate Scraper → Google Sheets
======================================================
Runs every 15 min via GitHub Actions. For each of the 20 configured list
pages it collects listings (1 page each), keeps only listings NOT already
in the sheet, then visits each new listing's detail page to fetch the
seller NAME and PHONE (both null-safe), and appends new rows to the sheet.

Required GitHub Secret (env var):
  WEBAPP_URL   – the URL of your Google Apps Script Web App (deployed from
                 the Sheet). The Web App handles dedup, append, and the
                 periodic clear inside the sheet itself.
"""

import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ── Configuration ──────────────────────────────────────────────────────────────

BASE_URL  = "https://www.kupujemprodajem.com"
PHONE_API = BASE_URL + "/api/web/v1/eds/{ad_id}/phone-number"

# The 20 list pages to scrape (1 page each per run).
LIST_URLS = [
    "https://www.kupujemprodajem.com/nekretnine-prodaja/placevi-i-zemljiste/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2828&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/placevi-i-zemljiste/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2828&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/kuce/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2828&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/kuce/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2823&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/kuce/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2823&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/stanovi/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2823&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/stanovi/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2822&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-prodaja/stanovi/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2822&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/poslovni-prostor/pretraga?page=1&order=posted%20desc&categoryId=2821&groupId=2822&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/poslovni-prostor/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2854&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/poslovni-prostor/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2854&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/kuce/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2854&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/kuce/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2853&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/kuce/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2853&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/stanovi/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2853&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/stanovi/pretraga?page=1&order=posted%20desc&categoryId=2850&groupId=2851&currency=eur&realEstateLocation=4243&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/stanovi/pretraga?page=1&categoryId=2850&groupId=2851&currency=eur&realEstateLocation=548&realEstateAdvertiserType=179",
    "https://www.kupujemprodajem.com/nekretnine-izdavanje/stanovi/pretraga?page=1&categoryId=2850&groupId=2851&currency=eur&realEstateLocation=4605&realEstateAdvertiserType=179&order=posted%20desc",
]

# Rotate through a few realistic desktop User-Agents.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

SHEET_NAME = "Listings"
SCOPES     = ["https://www.googleapis.com/auth/spreadsheets"]

# Polite, human-ish random delays (seconds).
DELAY_LIST_MIN,   DELAY_LIST_MAX   = 2.0, 5.0   # between the 20 list pages
DELAY_DETAIL_MIN, DELAY_DETAIL_MAX = 1.0, 3.0   # between detail-page fetches
REQUEST_TIMEOUT = 20


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class Listing:
    scraped_at: str
    ad_id:      str            # unique key – used to skip duplicates
    title:      Optional[str]  # KP "name" field, e.g. "Telep, Novi Sad"
    location:   Optional[str]  # same as title on KP list cards
    price:      Optional[str]
    area:       Optional[str]  # raw, e.g. "55 m²" or "5 ari" / "2 hektar"
    rooms:      Optional[str]
    floor:      Optional[str]
    advertiser: Optional[str]  # e.g. "Vlasnik"
    posted:     Optional[str]
    seller:     Optional[str]  # from detail page (null-safe)
    phone:      Optional[str]  # from phone API   (null-safe)
    url:        str

COLUMNS = [f.name for f in fields(Listing)]


# ── Scraper ────────────────────────────────────────────────────────────────────

class KPScraper:
    def __init__(self):
        self.session = requests.Session()

    def _headers(self):
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "sr-RS,sr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": BASE_URL,
        }

    def fetch_html(self, url):
        try:
            r = self.session.get(url, headers=self._headers(), timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return BeautifulSoup(r.text, "lxml")
        except requests.RequestException as e:
            print(f"  [!] Fetch failed ({url}): {e}", file=sys.stderr)
            return None

    @staticmethod
    def _text(el):
        return el.get_text(strip=True) if el else None

    # ── List-page parsing ──────────────────────────────────────────────────────

    def parse_card(self, section, ts):
        """Parse one <section> listing card. Stable selectors only."""
        try:
            ad_id = section.get("id") or ""
            link  = section.select_one("a[href*='/oglas/']")
            if not link or not ad_id:
                return None
            url = urljoin(BASE_URL, link.get("href", ""))

            # ad_id fallback: pull from URL if section id missing
            if not ad_id:
                m = re.search(r"/oglas/(\d+)", url)
                ad_id = m.group(1) if m else ""

            title = self._text(section.select_one("[class*='__name']"))
            price = self._text(section.select_one(".priceText")) \
                    or self._text(section.select_one("[class*='inlinePrice']"))

            # Attributes identified by their icon src (area / rooms / floor).
            area = rooms = floor = None
            for item in section.select("span[class*='SummaryItem'][class*='__item']"):
                icon = item.select_one("img")
                val  = self._text(item.select_one("[class*='__value']"))
                if not icon or val is None:
                    continue
                src = icon.get("src", "")
                if "area" in src:
                    area = val
                elif "rooms" in src:
                    rooms = val
                elif "floor" in src:
                    floor = val

            advertiser = self._text(section.select_one("[class*='AdItemImageTag']"))
            # Keep ONLY private-owner listings. Agencies/promoted slots that
            # leak into results have a different tag (or none) and are skipped.
            if (advertiser or "").strip().lower() != "vlasnik":
                return None

            posted     = self._text(section.select_one("[class*='postedStatus']"))

            return Listing(
                scraped_at = ts,
                ad_id      = str(ad_id),
                title      = title,
                location   = title,    # KP card "name" is the location string
                price      = price,
                area       = area,
                rooms      = rooms,
                floor      = floor,
                advertiser = advertiser,
                posted     = posted,
                seller     = None,     # filled later from detail page
                phone      = None,     # filled later from API
                url        = url,
            )
        except Exception as e:
            print(f"  [!] Parse error on card: {e}", file=sys.stderr)
            return None

    def parse_list_page(self, soup, ts):
        sections = soup.select("section[class*='adOuterHolder']")
        if not sections:  # fallback if class hash changes
            sections = [a.find_parent("section") for a in soup.select("a[href*='/oglas/']")]
        seen, out = set(), []
        for sec in sections:
            if not sec:
                continue
            sid = sec.get("id") or id(sec)
            if sid in seen:
                continue
            seen.add(sid)
            lst = self.parse_card(sec, ts)
            if lst:
                out.append(lst)
        return out

    def scrape_all_lists(self, ts):
        all_listings, seen_ids = [], set()
        for i, url in enumerate(LIST_URLS, 1):
            print(f"[{i}/{len(LIST_URLS)}] {url}")
            soup = self.fetch_html(url)
            if soup:
                for lst in self.parse_list_page(soup, ts):
                    if lst.ad_id not in seen_ids:   # de-dup within this run
                        seen_ids.add(lst.ad_id)
                        all_listings.append(lst)
            if i < len(LIST_URLS):
                time.sleep(random.uniform(DELAY_LIST_MIN, DELAY_LIST_MAX))
        return all_listings

    # ── Detail-page enrichment (name + phone), both null-safe ───────────────────

    def fetch_seller_name(self, detail_url):
        soup = self.fetch_html(detail_url)
        if not soup:
            return None
        el = soup.select_one("[class*='userName']")
        name = self._text(el)
        return name or None

    def fetch_phone(self, ad_id):
        try:
            headers = self._headers()
            headers["Accept"] = "application/json"
            headers["X-Requested-With"] = "XMLHttpRequest"
            r = self.session.get(PHONE_API.format(ad_id=ad_id),
                                 headers=headers, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return None
            data  = r.json()
            phone = data.get("phone") or ""
            return phone.strip() or None
        except (requests.RequestException, ValueError):
            return None

    def enrich(self, listings):
        total = len(listings)
        for i, lst in enumerate(listings, 1):
            lst.seller = self.fetch_seller_name(lst.url)
            lst.phone  = self.fetch_phone(lst.ad_id)
            print(f"  enrich {i}/{total}  id={lst.ad_id}  "
                  f"seller={lst.seller or '—'}  phone={lst.phone or '—'}")
            if i < total:
                time.sleep(random.uniform(DELAY_DETAIL_MIN, DELAY_DETAIL_MAX))
        return listings


# ── Send to Google Sheet via Apps Script Web App ────────────────────────────────

def post_to_webapp(listings):
    """POST new rows to the Apps Script Web App. The script does the append
    and de-duplication on the sheet side. Returns the parsed JSON response."""
    url = os.environ["WEBAPP_URL"]
    payload = {
        "columns": COLUMNS,
        "rows": [[("" if v is None else v) for v in asdict(l).values()] for l in listings],
    }
    r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text}


def get_existing_ids():
    """Ask the Web App which ad_ids are already in the sheet, so we only
    enrich + send genuinely new listings."""
    url = os.environ["WEBAPP_URL"]
    try:
        r = requests.get(url, params={"action": "ids"}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return set(str(x) for x in data.get("ids", []))
    except (requests.RequestException, ValueError) as e:
        print(f"  [!] Could not fetch existing ids ({e}); assuming none.", file=sys.stderr)
        return set()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\nKP scraper run @ {ts}\n")

    scraper = KPScraper()

    # 1. Collect listings from all 20 list pages (Vlasnik-only, deduped per run).
    listings = scraper.scrape_all_lists(ts)
    print(f"\nCollected {len(listings)} Vlasnik listings from list pages.")
    if not listings:
        print("Nothing collected – exiting.")
        return

    # 2. Ask the sheet which ad_ids it already has.
    existing = get_existing_ids()
    new = [l for l in listings if l.ad_id not in existing]
    print(f"New: {len(new)}   Already in sheet: {len(listings) - len(new)}\n")
    if not new:
        print("No new listings – exiting.")
        return

    # 3. Enrich ONLY the new ones with seller name + phone.
    print("Fetching seller name + phone for new listings…")
    scraper.enrich(new)

    # 4. Send to the sheet via the Web App.
    resp = post_to_webapp(new)
    print(f"\nWeb App response: {resp}")
    print("Done.")


if __name__ == "__main__":
    main()
