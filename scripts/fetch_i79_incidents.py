#!/usr/bin/env python3
"""Build an I-79 incident dataset from news and official WV511 delay listings."""

from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import re
from urllib.error import HTTPError
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "incidents.json"
DOCS_PATH = ROOT / "docs" / "incidents.json"
MANUAL_OVERRIDES_PATH = ROOT / "data" / "manual_overrides.json"

# Reliable local and regional sources with RSS endpoints.
RSS_FEEDS = [
    "https://www.wboy.com/feed/",
    "https://www.wdtv.com/rss",
    "https://wvmetronews.com/feed/",
]

WV511_DELAY_URL = "https://www.wv511.org/TravelConditions/TravelDelay.aspx"
WBOY_WP_API = "https://www.wboy.com/wp-json/wp/v2/posts"
WDTV_SITEMAP_INDEX_URL = "https://www.wdtv.com/arc/outboundfeeds/sitemap-index/?outputType=xml"
WDTV_NEWS_SITEMAP_BASE = "https://www.wdtv.com/arc/outboundfeeds/sitemap/category/news/?outputType=xml"
HISTORICAL_YEARS = 6
WBOY_SEARCH_TERMS = [
    "i-79 accident",
    "i-79 crash",
    "interstate 79 wreck",
    "i-79 marion county",
    "i-79 monongalia county",
    "i-79 harrison county",
]
NON_EVENT_TITLE_TERMS = {
    "discusses what might cause",
    "what might cause accidents",
    "safety tips",
    "how to avoid",
    "why crashes happen",
}
WDTV_URL_HINT_TERMS = ("i-79", "interstate-79")
NORTH_CENTRAL_COUNTIES = {"monongalia county", "marion county", "harrison county"}

KEYWORDS = [
    "i-79",
    "i 79",
    "interstate 79",
    "northbound",
    "southbound",
    "monongalia",
    "marion county",
    "harrison county",
    "bridgeport",
    "clarksburg",
    "fairmont",
    "weston",
]

INCIDENT_TERMS = [
    "accident",
    "crash",
    "wreck",
    "collision",
    "vehicle fire",
    "rolled over",
    "rollover",
    "tractor trailer",
    "traffic backup",
]

SPELLED_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}

CONSTRUCTION_TERMS = [
    "construction",
    "work zone",
    "bridge work",
    "bridge deck repairs",
    "paving",
    "lane closure",
    "detour",
    "road work",
    "maintenance",
]

LOCATION_HINTS = {
    "morgantown": {"lat": 39.6295, "lon": -79.9559},
    "star city": {"lat": 39.6579, "lon": -79.9862},
    "fairmont": {"lat": 39.4851, "lon": -80.1426},
    "white hall": {"lat": 39.4443, "lon": -80.1723},
    "bridgeport": {"lat": 39.2865, "lon": -80.2562},
    "clarksburg": {"lat": 39.2806, "lon": -80.3445},
    "weston": {"lat": 39.0384, "lon": -80.4673},
    "stonewood": {"lat": 39.2462, "lon": -80.3009},
    "lost creek": {"lat": 39.1615, "lon": -80.3731},
    "monongalia county": {"lat": 39.6525, "lon": -80.0041},
    "marion county": {"lat": 39.4568, "lon": -80.1542},
    "harrison county": {"lat": 39.3032, "lon": -80.3781},
}


@dataclass
class Incident:
    id: str
    title: str
    url: str
    source: str
    published_at: str
    summary: str
    location_text: str
    lat: float | None
    lon: float | None
    construction_related: bool
    suspected_fatalities: int
    source_type: str = "news"
    verification_status: str = "unverified"
    verified_fatalities: int | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "location_text": self.location_text,
            "lat": self.lat,
            "lon": self.lon,
            "construction_related": self.construction_related,
            "suspected_fatalities": self.suspected_fatalities,
            "source_type": self.source_type,
            "verification_status": self.verification_status,
            "verified_fatalities": self.verified_fatalities,
            "notes": self.notes,
        }


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_date(raw: str) -> str:
    if not raw:
        return ""
    parsed = email.utils.parsedate_to_datetime(raw)
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat()


def parse_wp_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat()


def parse_iso_date(raw: str) -> str:
    if not raw:
        return ""
    value = raw.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat()


def parse_wv511_date(raw: str) -> str:
    try:
        parsed = dt.datetime.strptime(raw.strip(), "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return ""
    return parsed.replace(tzinfo=dt.timezone.utc).isoformat()


def likely_relevant(text: str) -> bool:
    """Return True if text mentions I-79 and at least one incident keyword."""
    lowered = text.lower()
    mentions_i79 = "i-79" in lowered or "interstate 79" in lowered or "i 79" in lowered
    mentions_incident = any(term in lowered for term in INCIDENT_TERMS)
    return mentions_i79 and mentions_incident


def extract_fatalities(text: str) -> int:
    """Heuristically estimate fatality count from article text.

    Returns 0 if no fatal clues are found, or 1 if fatal language is present
    but no explicit count can be parsed.
    """
    lowered = text.lower()
    fatal_clues = [
        "fatal",
        "killed",
        "died",
        "dead",
        "medical examiner called",
        "pronounced dead",
        "dead at the scene",
        "dead at scene",
    ]
    if not any(clue in lowered for clue in fatal_clues):
        return 0

    patterns = [
        r"(\d+)\s+(?:people|person|victims?)\s+(?:were\s+)?killed",
        r"(\d+)\s+dead",
        r"killed\s+(\d+)",
        r"(\d+)\s+fatalit",
    ]

    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            value = int(match.group(1))
            if 0 < value <= 10:
                return value

    word_match = re.search(r"\b(one|two|three|four|five|six)\s+dead\b", lowered)
    if word_match:
        return SPELLED_NUMBERS[word_match.group(1)]

    word_match = re.search(r"\b(one|two|three|four|five|six)\s+(?:person|people)\s+(?:was|were)\s+killed\b", lowered)
    if word_match:
        return SPELLED_NUMBERS[word_match.group(1)]

    # A likely fatal crash mention with no explicit count.
    return 1


def infer_location(text: str) -> tuple[str, float | None, float | None]:
    """Extract a location name and approximate coordinates from free text.

    Prefers county-level matches; falls back to city/place name lookup.
    Returns (location_text, lat, lon) — lat/lon are None if no match found.
    """
    lowered = text.lower()
    county_matches: list[tuple[int, str]] = []
    for place in ("monongalia county", "marion county", "harrison county"):
        match = re.search(rf"\b{re.escape(place)}\b", lowered)
        if match:
            county_matches.append((match.start(), place))
    if county_matches:
        _, best = sorted(county_matches, key=lambda x: x[0])[0]
        coords = LOCATION_HINTS[best]
        return best.title(), coords["lat"], coords["lon"]
    for place, coords in LOCATION_HINTS.items():
        if place in lowered:
            return place.title(), coords["lat"], coords["lon"]
    return "Unspecified stretch", None, None


def incident_id(url: str, title: str) -> str:
    seed = f"{url}|{title}".encode("utf-8")
    return hashlib.sha1(seed).hexdigest()[:12]


def text_to_bool(value: str) -> bool:
    lowered = (value or "").strip().lower()
    return lowered in {"1", "true", "yes", "y"}


def iter_feed_items(feed_xml: bytes) -> Iterable[dict]:
    root = ET.fromstring(feed_xml)
    for item in root.findall(".//item"):
        title = clean_text(item.findtext("title", default=""))
        link = clean_text(item.findtext("link", default=""))
        description = clean_text(item.findtext("description", default=""))
        pub_date = clean_text(item.findtext("pubDate", default=""))
        source = clean_text(item.findtext("source", default=""))

        if not source:
            parsed = urllib.parse.urlparse(link)
            source = parsed.netloc.replace("www.", "") if parsed.netloc else "unknown"

        yield {
            "title": title,
            "link": link,
            "description": description,
            "pub_date": pub_date,
            "source": source,
        }


def fetch(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "i79-safety-monitor/1.0 (automated data pipeline)"},
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def fetch_json(url: str) -> object:
    return json.loads(fetch(url).decode("utf-8", errors="ignore"))


def parse_xml_bytes(raw: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def html_to_lines(page_html: str) -> list[str]:
    stripped = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", page_html)
    stripped = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", stripped)
    stripped = re.sub(r"(?i)<br\s*/?>", "\n", stripped)
    stripped = re.sub(r"(?i)</(div|li|p|td|tr|h1|h2|h3|h4|h5|h6|ul|ol|section)>", "\n", stripped)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    stripped = html.unescape(stripped)
    lines = []
    for line in stripped.splitlines():
        compact = re.sub(r"\s+", " ", line).strip()
        if compact:
            lines.append(compact)
    return lines


def parse_wv511_i79_incidents(lines: list[str]) -> list[Incident]:
    """Parse WV511 travel delay page (converted to text lines) into Incidents.

    Scans for blocks starting with 'I-79', extracts event title, county,
    description, and last-updated timestamp, then filters to north-central
    counties only.
    """
    incidents: list[Incident] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("I-79"):
            i += 1
            continue

        event_title = line.replace("I-79", "", 1).strip() or "Traffic Event"
        last_updated = ""
        county = ""
        description = ""
        notes = ""

        j = i + 1
        while j < len(lines):
            probe = lines[j]
            if probe.startswith("Last Updated:"):
                last_updated = probe.split(":", 1)[1].strip()
            elif probe.startswith("County:"):
                county = probe.split(":", 1)[1].strip()
            elif probe.startswith("Description:"):
                description = probe.split(":", 1)[1].strip()
            elif probe.startswith("Comments:"):
                notes = probe.split(":", 1)[1].strip()
            elif probe.startswith("I-") and not probe.startswith("I-79"):
                break
            elif probe.startswith("I-79"):
                break
            j += 1

        county_lower = county.lower()
        if county_lower not in NORTH_CENTRAL_COUNTIES:
            i = max(i + 1, j)
            continue

        blob = f"I-79 {event_title} {description} {notes}".strip()
        if description and "i-79" not in description.lower():
            i = max(i + 1, j)
            continue
        location_text, lat, lon = infer_location(f"{county} {blob}")
        fatalities = extract_fatalities(blob)
        construction_related = any(term in blob.lower() for term in CONSTRUCTION_TERMS)

        title = f"I-79 {event_title}".strip()
        pseudo_url = f"{WV511_DELAY_URL}#i79-{hashlib.sha1(blob.encode('utf-8')).hexdigest()[:10]}"
        incidents.append(
            Incident(
                id=incident_id(pseudo_url, title),
                title=title,
                url=WV511_DELAY_URL,
                source="wv511.org",
                published_at=parse_wv511_date(last_updated),
                summary=description,
                location_text=county or location_text,
                lat=lat,
                lon=lon,
                construction_related=construction_related,
                suspected_fatalities=fatalities,
                source_type="official_wv511",
                verification_status="official",
                notes=notes,
            )
        )
        i = max(i + 1, j)
    return incidents


def fetch_wv511_incidents() -> list[Incident]:
    try:
        raw = fetch(WV511_DELAY_URL).decode("utf-8", errors="ignore")
    except Exception:
        return []
    return parse_wv511_i79_incidents(html_to_lines(raw))


def is_north_central_context(text: str) -> bool:
    lowered = text.lower()
    county_hit = any(county in lowered for county in NORTH_CENTRAL_COUNTIES)
    county_alias_hit = any(alias in lowered for alias in ("mon county", "marion co", "harrison co"))
    city_hit = any(city in lowered for city in ("morgantown", "fairmont", "bridgeport", "clarksburg", "white hall", "weston"))
    return county_hit or county_alias_hit or city_hit


def iter_wboy_historical_posts() -> Iterable[dict]:
    """Yield raw WordPress post dicts from WBOY's public API.

    Searches each term in WBOY_SEARCH_TERMS across paginated results going
    back HISTORICAL_YEARS. Deduplicates by post ID across search terms.
    """
    after_date = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365 * HISTORICAL_YEARS)).isoformat()
    per_page = 100

    seen_post_ids: set[int] = set()
    for term in WBOY_SEARCH_TERMS:
        for page in range(1, 15):
            query = urllib.parse.urlencode(
                {
                    "search": term,
                    "per_page": per_page,
                    "page": page,
                    "after": after_date,
                    "_fields": "id,date_gmt,link,title,excerpt,content",
                }
            )
            url = f"{WBOY_WP_API}?{query}"
            try:
                payload = fetch_json(url)
            except HTTPError as exc:
                if exc.code == 400:
                    break
                continue
            except Exception:
                continue

            if not isinstance(payload, list) or not payload:
                break

            for row in payload:
                if not isinstance(row, dict):
                    continue
                post_id = row.get("id")
                if not isinstance(post_id, int) or post_id in seen_post_ids:
                    continue
                seen_post_ids.add(post_id)
                yield row


def to_wboy_incident(post: dict) -> Incident | None:
    title = clean_text(post.get("title", {}).get("rendered", "")) if isinstance(post.get("title"), dict) else ""
    link = clean_text(post.get("link", ""))
    excerpt = clean_text(post.get("excerpt", {}).get("rendered", "")) if isinstance(post.get("excerpt"), dict) else ""
    content = clean_text(post.get("content", {}).get("rendered", "")) if isinstance(post.get("content"), dict) else ""
    blob = f"{title} {excerpt} {content}".strip()
    title_excerpt_blob = f"{title} {excerpt}".strip()
    fatality_blob = f"{title} {excerpt} {content[:350]}".strip()
    title_lower = title.lower()

    if not title or not link:
        return None
    if any(term in title_lower for term in NON_EVENT_TITLE_TERMS):
        return None
    if not likely_relevant(title_excerpt_blob):
        return None
    if not is_north_central_context(blob):
        return None

    location_text, lat, lon = infer_location(blob)
    construction_related = any(term in blob.lower() for term in CONSTRUCTION_TERMS)
    fatalities = extract_fatalities(fatality_blob)

    return Incident(
        id=incident_id(link, title),
        title=title,
        url=link,
        source="wboy.com",
        published_at=parse_wp_date(str(post.get("date_gmt", ""))),
        summary=excerpt or content[:420],
        location_text=location_text,
        lat=lat,
        lon=lon,
        construction_related=construction_related,
        suspected_fatalities=fatalities,
        source_type="news_archive",
        verification_status="unverified",
    )


def extract_meta_content(html_text: str, key: str, property_attr: str = "property") -> str:
    pattern = rf'<meta[^>]+{property_attr}="{re.escape(key)}"[^>]+content="([^"]+)"'
    match = re.search(pattern, html_text, flags=re.IGNORECASE)
    return clean_text(match.group(1)) if match else ""


def iter_wdtv_sitemap_entries() -> Iterable[tuple[str, str]]:
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    seen_urls: set[str] = set()

    # First pass: explicit sitemap index links.
    try:
        root = parse_xml_bytes(fetch(WDTV_SITEMAP_INDEX_URL))
    except Exception:
        root = None
    if root is not None:
        for node in root.findall("sm:sitemap", ns):
            loc = node.findtext("sm:loc", default="", namespaces=ns).strip()
            if not loc:
                continue
            try:
                child = parse_xml_bytes(fetch(loc))
            except Exception:
                continue
            if child is None:
                continue
            for row in child.findall("sm:url", ns):
                article_url = row.findtext("sm:loc", default="", namespaces=ns).strip()
                lastmod = row.findtext("sm:lastmod", default="", namespaces=ns).strip()
                if article_url and article_url not in seen_urls:
                    seen_urls.add(article_url)
                    yield article_url, lastmod

    # Second pass: walk category/news pages for older entries, if available.
    empty_pages = 0
    for offset in range(0, 5100, 100):
        page_url = WDTV_NEWS_SITEMAP_BASE + (f"&from={offset}" if offset else "")
        try:
            root = parse_xml_bytes(fetch(page_url))
        except Exception:
            empty_pages += 1
            if empty_pages >= 3:
                break
            continue
        if root is None:
            empty_pages += 1
            if empty_pages >= 3:
                break
            continue

        rows = root.findall("sm:url", ns)
        if not rows:
            empty_pages += 1
            if empty_pages >= 3:
                break
            continue

        empty_pages = 0
        for row in rows:
            article_url = row.findtext("sm:loc", default="", namespaces=ns).strip()
            lastmod = row.findtext("sm:lastmod", default="", namespaces=ns).strip()
            if article_url and article_url not in seen_urls:
                seen_urls.add(article_url)
                yield article_url, lastmod


def to_wdtv_incident(article_url: str, sitemap_lastmod: str) -> Incident | None:
    try:
        page_html = fetch(article_url).decode("utf-8", errors="ignore")
    except Exception:
        return None

    title = extract_meta_content(page_html, "og:title")
    summary = extract_meta_content(page_html, "og:description")
    published_raw = extract_meta_content(page_html, "article:published_time")
    if not published_raw:
        published_raw = sitemap_lastmod

    if not title:
        title_match = re.search(r"<title>([^<]+)</title>", page_html, flags=re.IGNORECASE)
        title = clean_text(title_match.group(1)) if title_match else ""

    if not title:
        return None

    blob = f"{title} {summary} {article_url}"
    if not likely_relevant(blob):
        return None
    if not is_north_central_context(blob):
        return None

    location_text, lat, lon = infer_location(blob)
    construction_related = any(term in blob.lower() for term in CONSTRUCTION_TERMS)
    fatalities = extract_fatalities(f"{title} {summary}")

    return Incident(
        id=incident_id(article_url, title),
        title=title,
        url=article_url,
        source="wdtv.com",
        published_at=parse_iso_date(published_raw),
        summary=summary,
        location_text=location_text,
        lat=lat,
        lon=lon,
        construction_related=construction_related,
        suspected_fatalities=fatalities,
        source_type="news_archive_wdtv",
        verification_status="unverified",
    )


def fetch_wdtv_historical_incidents() -> list[Incident]:
    incidents: list[Incident] = []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=365 * HISTORICAL_YEARS)

    for article_url, lastmod in iter_wdtv_sitemap_entries():
        lowered_url = article_url.lower()
        if not any(term in lowered_url for term in WDTV_URL_HINT_TERMS):
            continue
        incident = to_wdtv_incident(article_url, lastmod)
        if not incident:
            continue
        if incident.published_at:
            try:
                when = dt.datetime.fromisoformat(incident.published_at.replace("Z", "+00:00"))
            except ValueError:
                when = None
            if when and when < cutoff:
                continue
        incidents.append(incident)

    return incidents


def load_manual_overrides() -> dict:
    if not MANUAL_OVERRIDES_PATH.exists():
        return {"incident_overrides": {}, "manual_incidents": []}
    try:
        payload = json.loads(MANUAL_OVERRIDES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"incident_overrides": {}, "manual_incidents": []}
    if not isinstance(payload, dict):
        return {"incident_overrides": {}, "manual_incidents": []}
    payload.setdefault("incident_overrides", {})
    payload.setdefault("manual_incidents", [])
    return payload


def apply_manual_overrides(incidents: list[Incident], payload: dict) -> list[Incident]:
    """Apply patches and hand-entered records from manual_overrides.json.

    Supports two operations:
    - incident_overrides: patch specific fields on an existing incident by ID
    - manual_incidents: inject fully hand-curated incident records
    """
    by_id = {incident.id: incident for incident in incidents}

    for incident_id_key, patch in payload.get("incident_overrides", {}).items():
        incident = by_id.get(incident_id_key)
        if not incident or not isinstance(patch, dict):
            continue

        if "construction_related" in patch:
            incident.construction_related = bool(patch["construction_related"])
        if "suspected_fatalities" in patch:
            incident.suspected_fatalities = int(patch["suspected_fatalities"])
        if "verified_fatalities" in patch:
            value = patch["verified_fatalities"]
            incident.verified_fatalities = int(value) if value is not None else None
        if "verification_status" in patch:
            incident.verification_status = str(patch["verification_status"])
        if "notes" in patch:
            incident.notes = str(patch["notes"])

    for raw in payload.get("manual_incidents", []):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title", "")).strip()
        url = str(raw.get("url", "manual://local")).strip() or "manual://local"
        if not title:
            continue
        text_blob = f"{title} {raw.get('summary', '')}"
        location_text, lat, lon = infer_location(text_blob)
        incident = Incident(
            id=incident_id(url, title),
            title=title,
            url=url,
            source=str(raw.get("source", "manual")),
            published_at=str(raw.get("published_at", "")),
            summary=str(raw.get("summary", "")),
            location_text=str(raw.get("location_text", location_text)),
            lat=raw.get("lat", lat),
            lon=raw.get("lon", lon),
            construction_related=text_to_bool(str(raw.get("construction_related", "false"))),
            suspected_fatalities=int(raw.get("suspected_fatalities", 0)),
            source_type=str(raw.get("source_type", "manual")),
            verification_status=str(raw.get("verification_status", "verified")),
            verified_fatalities=raw.get("verified_fatalities"),
            notes=str(raw.get("notes", "")),
        )
        by_id[incident.id] = incident

    return list(by_id.values())


def effective_fatalities(incident: Incident) -> int:
    if isinstance(incident.verified_fatalities, int):
        return incident.verified_fatalities
    return incident.suspected_fatalities


def build_dataset() -> dict:
    """Ingest all sources, deduplicate, apply overrides, and return the full dataset dict."""
    incidents: list[Incident] = []
    seen: set[str] = set()

    for feed in RSS_FEEDS:
        try:
            xml_bytes = fetch(feed)
        except Exception:
            continue

        for item in iter_feed_items(xml_bytes):
            blob = f"{item['title']} {item['description']}"
            if not likely_relevant(blob):
                continue

            url = item["link"]
            if not url:
                continue

            iid = incident_id(url, item["title"])
            if iid in seen:
                continue
            seen.add(iid)

            location_text, lat, lon = infer_location(blob)
            construction_related = any(term in blob.lower() for term in CONSTRUCTION_TERMS)
            fatalities = extract_fatalities(blob)

            incidents.append(
                Incident(
                    id=iid,
                    title=item["title"],
                    url=url,
                    source=item["source"],
                    published_at=parse_date(item["pub_date"]),
                    summary=item["description"],
                    location_text=location_text,
                    lat=lat,
                    lon=lon,
                    construction_related=construction_related,
                    suspected_fatalities=fatalities,
                    source_type="news",
                    verification_status="unverified",
                )
            )

    incidents.extend(fetch_wv511_incidents())
    for incident in fetch_wdtv_historical_incidents():
        if incident.id in seen:
            continue
        seen.add(incident.id)
        incidents.append(incident)

    for post in iter_wboy_historical_posts():
        incident = to_wboy_incident(post)
        if not incident:
            continue
        if incident.id in seen:
            continue
        seen.add(incident.id)
        incidents.append(incident)

    incidents = apply_manual_overrides(incidents, load_manual_overrides())
    incidents.sort(key=lambda x: x.published_at or "", reverse=True)

    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "incident_count": len(incidents),
        "suspected_fatalities": sum(effective_fatalities(i) for i in incidents),
        "construction_related_count": sum(1 for i in incidents if i.construction_related),
        "official_source_count": sum(1 for i in incidents if i.source_type == "official_wv511"),
        "verified_count": sum(1 for i in incidents if i.verification_status in {"official", "verified"}),
    }

    return {
        "summary": summary,
        "incidents": [i.to_dict() for i in incidents],
    }


def write_dataset(payload: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)

    body = json.dumps(payload, indent=2)
    DATA_PATH.write_text(body, encoding="utf-8")
    DOCS_PATH.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    write_dataset(build_dataset())
