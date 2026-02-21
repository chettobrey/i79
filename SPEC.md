# I-79 Safety Monitor — System Specification

## Purpose

Automatically aggregate and display reported crashes and fatalities along Interstate 79 in Monongalia, Marion, and Harrison counties (North Central West Virginia). Published as a static GitHub Pages site, refreshed every 6 hours via GitHub Actions.

---

## File Map

| File | Responsibility |
|------|----------------|
| `scripts/fetch_i79_incidents.py` | All data ingestion, filtering, and JSON output. No external dependencies — stdlib only. |
| `data/incidents.json` | Canonical generated dataset (source of truth). |
| `data/manual_overrides.json` | Hand-curated corrections and additions applied at build time. |
| `docs/incidents.json` | Copy of `data/incidents.json` served by GitHub Pages. |
| `docs/index.html` | Static dashboard shell. |
| `docs/app.js` | Frontend: map, timeline chart, filter buttons, incident list. |
| `docs/styles.css` | Responsive styles using CSS custom properties. |
| `.github/workflows/refresh-data.yml` | Scheduled and manual-trigger GitHub Actions workflow. |

---

## Data Sources

| ID | Source | Endpoint | Type |
|----|--------|----------|------|
| `news` | WBOY, WDTV, WV MetroNews RSS | See `RSS_FEEDS` constant | RSS/XML |
| `news_archive` | WBOY WordPress API | `WBOY_WP_API` | JSON/paginated |
| `news_archive_wdtv` | WDTV Arc sitemap | `WDTV_SITEMAP_INDEX_URL` | XML sitemap |
| `official_wv511` | WV511 Travel Delays | `WV511_DELAY_URL` | HTML |

---

## Filtering Requirements

An incident is included only when ALL of the following are true:

1. **I-79 mention**: text contains `i-79`, `interstate 79`, or `i 79` (case-insensitive).
2. **Incident keyword**: text contains at least one term from `INCIDENT_TERMS` (accident, crash, wreck, collision, vehicle fire, rollover, tractor trailer, traffic backup).
3. **North-central context**: text references Monongalia, Marion, or Harrison county, or a major city in those counties (Morgantown, Fairmont, Bridgeport, Clarksburg, White Hall, Weston).
4. **Non-editorial title**: title does not match `NON_EVENT_TITLE_TERMS` (opinion/advice articles excluded).

WV511 incidents must additionally have a county matching `NORTH_CENTRAL_COUNTIES` exactly.

---

## Incident Data Schema

Each incident in `incidents` array has these fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (12-char hex) | SHA1 of `url + title`, truncated. Stable across runs. |
| `title` | string | Article or event headline. |
| `url` | string | Canonical link to source article or WV511 page. |
| `source` | string | Domain (e.g. `wboy.com`, `wv511.org`). |
| `published_at` | ISO 8601 string | UTC publication time. Empty string if unknown. |
| `summary` | string | Short excerpt or event description. |
| `location_text` | string | Human-readable location (county or city name). |
| `lat` | number or null | Approximate latitude (inferred from place name). |
| `lon` | number or null | Approximate longitude. |
| `construction_related` | boolean | True if any `CONSTRUCTION_TERMS` appear in text. |
| `suspected_fatalities` | integer | Heuristic count from article text (0 if none detected). |
| `source_type` | string | One of: `news`, `news_archive`, `news_archive_wdtv`, `official_wv511`, `manual`. |
| `verification_status` | string | One of: `unverified`, `official`, `verified`. |
| `verified_fatalities` | integer or null | Manual override; takes precedence over `suspected_fatalities` in UI. |
| `notes` | string | Curator notes, populated via manual overrides. |

### Output envelope

```json
{
  "summary": {
    "generated_at": "<ISO 8601>",
    "incident_count": 0,
    "suspected_fatalities": 0,
    "construction_related_count": 0,
    "official_source_count": 0,
    "verified_count": 0
  },
  "incidents": []
}
```

---

## Fatality Extraction Rules (`extract_fatalities`)

Applied to a text blob composed of title + excerpt/summary + first 350 chars of body.

1. If no fatal clue word is present (`fatal`, `killed`, `died`, `dead`, `pronounced dead`, `medical examiner called`), return **0**.
2. If a numeric count pattern matches (`2 dead`, `killed 3`, `1 fatality`), return that count (capped at 10).
3. If a spelled-out count matches (`one dead`, `three people were killed`) using `SPELLED_NUMBERS`, return that count.
4. If a fatal clue is present but no count found, return **1** (conservative default).

---

## Location Inference Rules (`infer_location`)

Applied to a combined text blob of title + summary + full content.

1. Search for county names (`monongalia county`, `marion county`, `harrison county`). Use the earliest match. Return county-level coordinates from `LOCATION_HINTS`.
2. Fall back to city/place name lookup from `LOCATION_HINTS` keys.
3. If no match found, return `("Unspecified stretch", None, None)`.

---

## Manual Override Format (`data/manual_overrides.json`)

```json
{
  "incident_overrides": {
    "<12-char incident id>": {
      "verified_fatalities": 1,
      "verification_status": "verified",
      "construction_related": false,
      "suspected_fatalities": 1,
      "notes": "Confirmed by WVSP press release 2024-03-15"
    }
  },
  "manual_incidents": [
    {
      "title": "Fatal crash on I-79 near Fairmont",
      "url": "https://example.com/article",
      "source": "wvsp.gov",
      "published_at": "2024-03-15T14:00:00+00:00",
      "summary": "One person killed.",
      "location_text": "Marion County",
      "lat": 39.4568,
      "lon": -80.1542,
      "construction_related": false,
      "suspected_fatalities": 1,
      "source_type": "manual",
      "verification_status": "verified",
      "verified_fatalities": 1,
      "notes": ""
    }
  ]
}
```

---

## Frontend Features (`docs/app.js`)

| Feature | Behavior |
|---------|----------|
| Map | Leaflet.js map centered on North Central WV (`[39.38, -80.2]`, zoom 9). Circle markers color-coded: red = suspected/verified fatality, orange = construction-related, blue = other. |
| Filter buttons | Four modes: `all`, `construction`, `fatal` (verified_fatalities or suspected_fatalities > 0), `official` (source_type = `official_wv511`). |
| Timeline chart | SVG bar chart of monthly incident counts, last 18 months. Red line overlay for monthly fatality counts. |
| Stats bar | Live counts for filtered set: incidents, fatalities, construction-related, official. |
| Incident list | Scrollable list with title link, date, source, location, badges, and notes. |
| Data refresh | Fetches `./incidents.json` with `cache: "no-store"` on page load. |

---

## Automation (`refresh-data.yml`)

- **Schedule**: every 6 hours (`0 */6 * * *` UTC).
- **Manual trigger**: `workflow_dispatch`.
- **Python version**: 3.12.
- **Commit behavior**: only commits if `data/` or `docs/incidents.json` changed.
- **Bot identity**: `github-actions[bot]`.
- **Permission scope**: `contents: write` only.

---

## Constraints

- **No external Python dependencies.** The script uses stdlib only (`urllib`, `xml.etree.ElementTree`, `hashlib`, `re`, `json`, `dataclasses`, `pathlib`).
- **No database.** All state is stored in `data/incidents.json` and `data/manual_overrides.json`.
- **No authentication.** All data sources are public.
- **Static site only.** `docs/` is served as-is by GitHub Pages; no server-side logic.
- **Deduplication by ID.** Incidents are keyed by `SHA1(url + title)[:12]`. Identical articles from multiple sources will collapse to one.
- **Historical window**: `HISTORICAL_YEARS = 6` years back from current date.
- **Geography**: strictly scoped to Monongalia, Marion, and Harrison counties. Incidents in other WV counties are excluded.
