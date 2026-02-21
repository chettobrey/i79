# I-79 Safety Monitor (North Central West Virginia)

[![Refresh I-79 Dataset](https://github.com/chettobrey/i79/actions/workflows/refresh-data.yml/badge.svg)](https://github.com/chettobrey/i79/actions/workflows/refresh-data.yml)

**Live dashboard:** https://chettobrey.github.io/i79/

Public dashboard for tracking reported crashes and potential fatalities along Interstate 79 in Monongalia, Marion, and Harrison counties.

## What this project does

- Pulls stories from local/regional RSS feeds (`WBOY`, `WDTV`, `WV MetroNews`)
- Pulls multi-year WBOY historical stories via WordPress API search
- Pulls WDTV historical I-79 stories discoverable via Arc sitemap endpoints
- Pulls official roadway events from WV511's public `Possible Travel Delays` listing
- Filters for likely I-79 crash-related reports
- Tags likely construction/work-zone incidents
- Estimates fatality counts from article text (heuristic)
- Supports manual verification/override workflow (`data/manual_overrides.json`)
- Publishes a map + timeline + list view in a static site (`docs/`)
- Auto-refreshes the dataset every 6 hours using GitHub Actions

## Project structure

- `scripts/fetch_i79_incidents.py`: ingest + filter + output JSON
- `data/incidents.json`: canonical generated data file
- `data/manual_overrides.json`: optional manual corrections and hand-entered incidents
- `docs/index.html`: dashboard page
- `docs/app.js`: frontend logic (map, timeline chart, filters, stats)
- `docs/styles.css`: styling
- `.github/workflows/refresh-data.yml`: scheduled refresh

## Local run

1. Generate data:

```bash
python scripts/fetch_i79_incidents.py
```

2. Serve `docs/` locally:

```bash
python -m http.server 8080 --directory docs
```

3. Open `http://localhost:8080`

Notes:

- Historical ingestion can take around 30–90 seconds depending on network conditions.
- If a source endpoint is temporarily unavailable, the script continues with remaining sources.

## Deploy to GitHub Pages

1. Push this repo to GitHub.
2. In repository settings, enable GitHub Pages:
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/docs`
3. In Actions, run `Refresh I-79 Dataset` once manually (`workflow_dispatch`).
4. Your site will be live at `https://<your-user>.github.io/<repo>/`.

## Reliability and limitations

- This is an awareness dashboard, not an official crash database.
- WV511 records are official roadway delay events but not all are crashes or fatal incidents.
- News-derived fatality counts are heuristic and should be treated as provisional.
- Location coordinates are inferred from place names and may be approximate.
- WDTV historical coverage depends on what is exposed in Arc sitemap endpoints and may be incomplete for older years.
- Duplicate stories across sources can still occur.
- Always cross-check major claims with WV511, WVSP releases, and county 911/public safety updates.

## Manual verification queue

Use `data/manual_overrides.json` to:

- Patch an incident by ID (set `verified_fatalities`, `verification_status`, etc.)
- Add a manually curated incident if a source is missing from automation

Example:

```json
{
  "incident_overrides": {
    "d72324d9ed20": {
      "verified_fatalities": 1,
      "verification_status": "verified",
      "notes": "Confirmed by WVSP press release 2024-03-15"
    }
  },
  "manual_incidents": []
}
```

After edits, rerun:

```bash
python scripts/fetch_i79_incidents.py
```

## Recommended next upgrades

- Add WVSP and county emergency-management press-release ingestion for stronger historical coverage.
- Add deduplication by roadway segment + date to merge multi-source reports of the same event.
- Add county-level aggregation view.
- Add source quality scoring and duplicate-cluster detection.

## License

MIT — see [LICENSE](LICENSE).

## Author

[Chet Tobrey](https://github.com/chettobrey)
