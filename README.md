# KupujemProdajem → Google Sheets Scraper

Runs every 15 minutes on GitHub Actions. Scrapes 20 real-estate list pages
(1 page each), and for every listing **not already in the sheet**, visits its
detail page to fetch the seller **name** and **phone**, then appends the new
rows. The sheet is wiped every 2 days (header kept).

## What gets captured per listing
`scraped_at, ad_id, title, location, price, area, rooms, floor, advertiser,
posted, seller, phone, url`

- `ad_id` is the listing's unique ID (also used to skip duplicates).
- `area` keeps the raw value, so plots showing `ari`/`hektar` are preserved.
- `seller` and `phone` are **null-safe** — if a listing has neither, those
  cells are simply left blank instead of erroring.

## Files
- `scraper.py`        – main scraper
- `clear_sheet.py`    – wipes data rows (runs every 2 days)
- `requirements.txt`  – Python deps
- `.github/workflows/scrape.yml` – the 15-min schedule
- `.github/workflows/clear.yml`  – the 2-day wipe

## Setup (one-time)

### 1. Repo
Create a GitHub repo (Public = unlimited Actions minutes) and upload all files,
keeping the `.github/workflows/` folder structure intact.

### 2. Google Service Account
1. console.cloud.google.com → new project
2. Enable **Google Sheets API**
3. IAM & Admin → Service Accounts → create one → **Keys → Add key → JSON** → download

### 3. Google Sheet
1. Create a blank sheet
2. Copy its ID from the URL (between `/d/` and `/edit`)
3. Share the sheet with the service-account email (Editor)

### 4. GitHub Secrets
Repo → Settings → Secrets and variables → Actions:
- `GOOGLE_SERVICE_ACCOUNT_JSON` → paste the whole JSON file contents
- `SPREADSHEET_ID` → the sheet ID

### 5. Test
Actions tab → **KP Real Estate Scraper** → Run workflow. Check the sheet.

## Notes on timing & limits
- ~20 list pages + N detail fetches per run, with randomized delays
  (2–5s between list pages, 1–3s between detail pages) and rotating
  User-Agents to stay polite and under KP's radar.
- After the first run, most listings are already in the sheet, so each run only
  fetches detail pages for genuinely new listings — keeping runs short.
- Public repo → unlimited free minutes. Private repo free tier is 2,000
  min/month; every-15-min may exceed it, so prefer Public or widen to `*/20`.

## If KP changes their HTML
The scraper matches on stable class **substrings** (e.g. `adOuterHolder`,
`__name`, `priceText`, `postedStatus`) and identifies area/rooms/floor by the
attribute **icon filename** (`area.svg` / `rooms.svg` / `floor.svg`) rather than
fragile full class names. If listings stop appearing, re-grab one card's HTML
and the selectors can be quickly adjusted.
