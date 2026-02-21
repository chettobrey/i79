#!/usr/bin/env python3
"""Unit tests for scripts/fetch_i79_incidents.py.

Run with:
    python -m pytest tests/
    python -m unittest discover tests/

Tests cover all pure functions. No network calls are made.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from fetch_i79_incidents import (
    Incident,
    apply_manual_overrides,
    clean_text,
    extract_fatalities,
    html_to_lines,
    incident_id,
    infer_location,
    is_north_central_context,
    iter_feed_items,
    likely_relevant,
    parse_iso_date,
    parse_wv511_date,
    parse_wv511_i79_incidents,
    parse_wp_date,
    text_to_bool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_incident(**kwargs) -> Incident:
    defaults = dict(
        id="abc123def456",
        title="Test crash",
        url="https://example.com/article",
        source="example.com",
        published_at="2025-01-01T00:00:00+00:00",
        summary="A crash on I-79.",
        location_text="Marion County",
        lat=39.4568,
        lon=-80.1542,
        construction_related=False,
        suspected_fatalities=0,
    )
    defaults.update(kwargs)
    return Incident(**defaults)


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

class TestCleanText(unittest.TestCase):

    def test_strips_html_tags(self):
        from fetch_i79_incidents import clean_text
        self.assertEqual(clean_text("<p>Hello <b>world</b></p>"), "Hello world")

    def test_collapses_whitespace(self):
        from fetch_i79_incidents import clean_text
        self.assertEqual(clean_text("  lots   of   spaces  "), "lots of spaces")

    def test_empty_string(self):
        from fetch_i79_incidents import clean_text
        self.assertEqual(clean_text(""), "")

    def test_no_tags_passthrough(self):
        from fetch_i79_incidents import clean_text
        self.assertEqual(clean_text("plain text"), "plain text")

    def test_none_treated_as_empty(self):
        from fetch_i79_incidents import clean_text
        self.assertEqual(clean_text(None), "")


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

class TestParseDateFunctions(unittest.TestCase):

    def test_parse_wp_date_with_naive_datetime(self):
        result = parse_wp_date("2025-06-15T12:30:00")
        self.assertIn("2025-06-15", result)
        self.assertIn("12:30:00", result)

    def test_parse_wp_date_with_z_suffix(self):
        result = parse_wp_date("2025-06-15T12:30:00Z")
        self.assertIn("2025-06-15", result)

    def test_parse_wp_date_empty(self):
        self.assertEqual(parse_wp_date(""), "")

    def test_parse_wp_date_invalid(self):
        self.assertEqual(parse_wp_date("not-a-date"), "")

    def test_parse_iso_date_with_offset(self):
        result = parse_iso_date("2025-06-15T12:30:00+00:00")
        self.assertIn("2025-06-15", result)
        self.assertIn("12:30:00", result)

    def test_parse_iso_date_with_z(self):
        result = parse_iso_date("2025-06-15T12:30:00Z")
        self.assertIn("2025-06-15", result)

    def test_parse_iso_date_empty(self):
        self.assertEqual(parse_iso_date(""), "")

    def test_parse_iso_date_invalid(self):
        self.assertEqual(parse_iso_date("garbage"), "")

    def test_parse_wv511_date_valid(self):
        result = parse_wv511_date("06/15/2025 02:30:00 PM")
        self.assertIn("2025-06-15", result)
        self.assertIn("14:30:00", result)

    def test_parse_wv511_date_invalid(self):
        self.assertEqual(parse_wv511_date("bad date"), "")


# ---------------------------------------------------------------------------
# likely_relevant
# ---------------------------------------------------------------------------

class TestLikelyRelevant(unittest.TestCase):

    def test_i79_and_crash(self):
        self.assertTrue(likely_relevant("I-79 crash near Morgantown"))

    def test_interstate_79_and_accident(self):
        self.assertTrue(likely_relevant("Interstate 79 accident blocks traffic"))

    def test_i_space_79_and_wreck(self):
        self.assertTrue(likely_relevant("I 79 wreck closes northbound lanes"))

    def test_i79_no_incident_term(self):
        self.assertFalse(likely_relevant("I-79 construction update"))

    def test_crash_no_i79(self):
        self.assertFalse(likely_relevant("car crash on Route 50 near Clarksburg"))

    def test_empty_string(self):
        self.assertFalse(likely_relevant(""))

    def test_case_insensitive(self):
        self.assertTrue(likely_relevant("INTERSTATE 79 ROLLOVER"))


# ---------------------------------------------------------------------------
# extract_fatalities
# ---------------------------------------------------------------------------

class TestExtractFatalities(unittest.TestCase):

    def test_no_fatal_clue(self):
        self.assertEqual(extract_fatalities("Traffic backup on I-79 near Fairmont"), 0)

    def test_numeric_dead(self):
        self.assertEqual(extract_fatalities("2 dead in I-79 crash"), 2)

    def test_numeric_killed(self):
        self.assertEqual(extract_fatalities("Crash killed 3 on I-79"), 3)

    def test_numeric_fatality(self):
        self.assertEqual(extract_fatalities("1 fatality reported on I-79"), 1)

    def test_numeric_people_killed(self):
        self.assertEqual(extract_fatalities("2 people were killed in the crash"), 2)

    def test_spelled_one_dead(self):
        self.assertEqual(extract_fatalities("one dead after I-79 collision"), 1)

    def test_spelled_three_dead(self):
        self.assertEqual(extract_fatalities("three dead following overnight wreck"), 3)

    def test_spelled_two_people_killed(self):
        self.assertEqual(extract_fatalities("two people were killed in the accident"), 2)

    def test_fatal_clue_no_count_defaults_to_one(self):
        self.assertEqual(extract_fatalities("fatal crash on I-79"), 1)

    def test_pronounced_dead_no_count(self):
        self.assertEqual(extract_fatalities("Driver pronounced dead at the scene"), 1)

    def test_medical_examiner_called(self):
        self.assertEqual(extract_fatalities("Medical examiner called to the scene of the crash"), 1)

    def test_count_capped_at_ten(self):
        # 15 dead should return 0 since value > 10 is filtered out; falls back to 1 from fatal clue
        self.assertEqual(extract_fatalities("15 dead in massive pileup"), 1)


# ---------------------------------------------------------------------------
# infer_location
# ---------------------------------------------------------------------------

class TestInferLocation(unittest.TestCase):

    def test_marion_county(self):
        loc, lat, lon = infer_location("Crash in Marion County on I-79")
        self.assertEqual(loc, "Marion County")
        self.assertAlmostEqual(lat, 39.4568, places=3)
        self.assertAlmostEqual(lon, -80.1542, places=3)

    def test_monongalia_county(self):
        loc, lat, lon = infer_location("I-79 accident in Monongalia County")
        self.assertEqual(loc, "Monongalia County")

    def test_harrison_county(self):
        loc, lat, lon = infer_location("Harrison County crash")
        self.assertEqual(loc, "Harrison County")

    def test_city_morgantown(self):
        loc, lat, lon = infer_location("Crash near Morgantown on I-79")
        self.assertEqual(loc, "Morgantown")
        self.assertAlmostEqual(lat, 39.6295, places=3)

    def test_city_fairmont(self):
        loc, lat, lon = infer_location("I-79 wreck near Fairmont")
        self.assertEqual(loc, "Fairmont")

    def test_city_bridgeport(self):
        loc, lat, lon = infer_location("Accident near Bridgeport")
        self.assertEqual(loc, "Bridgeport")

    def test_county_preferred_over_city(self):
        # County should win over city when both present
        loc, lat, lon = infer_location("Marion County crash near Fairmont")
        self.assertEqual(loc, "Marion County")

    def test_no_match_returns_unspecified(self):
        loc, lat, lon = infer_location("Crash on some unnamed stretch")
        self.assertEqual(loc, "Unspecified stretch")
        self.assertIsNone(lat)
        self.assertIsNone(lon)


# ---------------------------------------------------------------------------
# incident_id
# ---------------------------------------------------------------------------

class TestIncidentId(unittest.TestCase):

    def test_returns_12_char_hex(self):
        iid = incident_id("https://example.com/article", "Test Title")
        self.assertEqual(len(iid), 12)
        self.assertRegex(iid, r"^[0-9a-f]{12}$")

    def test_same_inputs_same_id(self):
        iid1 = incident_id("https://example.com/article", "Test Title")
        iid2 = incident_id("https://example.com/article", "Test Title")
        self.assertEqual(iid1, iid2)

    def test_different_urls_different_id(self):
        iid1 = incident_id("https://example.com/article-1", "Test Title")
        iid2 = incident_id("https://example.com/article-2", "Test Title")
        self.assertNotEqual(iid1, iid2)

    def test_different_titles_different_id(self):
        iid1 = incident_id("https://example.com/article", "Title A")
        iid2 = incident_id("https://example.com/article", "Title B")
        self.assertNotEqual(iid1, iid2)


# ---------------------------------------------------------------------------
# text_to_bool
# ---------------------------------------------------------------------------

class TestTextToBool(unittest.TestCase):

    def test_true_values(self):
        for val in ("true", "True", "TRUE", "1", "yes", "Yes", "y", "Y"):
            self.assertTrue(text_to_bool(val), f"Expected True for {val!r}")

    def test_false_values(self):
        for val in ("false", "False", "0", "no", "", "maybe"):
            self.assertFalse(text_to_bool(val), f"Expected False for {val!r}")

    def test_none(self):
        self.assertFalse(text_to_bool(None))


# ---------------------------------------------------------------------------
# html_to_lines
# ---------------------------------------------------------------------------

class TestHtmlToLines(unittest.TestCase):

    def test_strips_script_tags(self):
        html = "<script>alert('xss')</script><p>Safe content</p>"
        lines = html_to_lines(html)
        self.assertTrue(any("Safe content" in l for l in lines))
        self.assertFalse(any("alert" in l for l in lines))

    def test_strips_style_tags(self):
        html = "<style>body { color: red; }</style><p>Content</p>"
        lines = html_to_lines(html)
        self.assertFalse(any("color" in l for l in lines))

    def test_br_becomes_new_line(self):
        html = "Line one<br>Line two<br/>Line three"
        lines = html_to_lines(html)
        self.assertGreaterEqual(len(lines), 2)

    def test_block_elements_split_lines(self):
        html = "<p>Para one</p><p>Para two</p>"
        lines = html_to_lines(html)
        self.assertGreaterEqual(len(lines), 2)

    def test_strips_remaining_tags(self):
        html = "<span class='x'>Text <b>bold</b> end</span>"
        lines = html_to_lines(html)
        self.assertEqual(lines[0], "Text bold end")

    def test_empty_lines_excluded(self):
        html = "<p></p><p>  </p><p>Content</p>"
        lines = html_to_lines(html)
        for line in lines:
            self.assertTrue(line.strip())

    def test_html_entities_unescaped(self):
        html = "<p>I-79 &amp; Route 50</p>"
        lines = html_to_lines(html)
        self.assertTrue(any("I-79 & Route 50" in l for l in lines))


# ---------------------------------------------------------------------------
# iter_feed_items
# ---------------------------------------------------------------------------

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>I-79 crash near Fairmont</title>
      <link>https://www.wboy.com/news/i79-crash-fairmont</link>
      <description>A crash on I-79 southbound in Marion County.</description>
      <pubDate>Mon, 10 Feb 2025 14:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Construction update on I-79</title>
      <link>https://www.wdtv.com/news/i79-construction</link>
      <description>Lane closures expected through the weekend.</description>
      <pubDate>Tue, 11 Feb 2025 09:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>"""


class TestIterFeedItems(unittest.TestCase):

    def setUp(self):
        self.items = list(iter_feed_items(SAMPLE_RSS))

    def test_yields_expected_count(self):
        self.assertEqual(len(self.items), 2)

    def test_first_item_title(self):
        self.assertEqual(self.items[0]["title"], "I-79 crash near Fairmont")

    def test_first_item_link(self):
        self.assertIn("wboy.com", self.items[0]["link"])

    def test_source_extracted_from_url(self):
        # No <source> element in XML, so source should be extracted from link domain
        self.assertEqual(self.items[0]["source"], "wboy.com")

    def test_second_item_description(self):
        self.assertIn("Lane closures", self.items[1]["description"])

    def test_pub_date_present(self):
        self.assertTrue(self.items[0]["pub_date"])


# ---------------------------------------------------------------------------
# is_north_central_context
# ---------------------------------------------------------------------------

class TestIsNorthCentralContext(unittest.TestCase):

    def test_monongalia_county(self):
        self.assertTrue(is_north_central_context("Crash in Monongalia County"))

    def test_marion_county(self):
        self.assertTrue(is_north_central_context("Marion County accident"))

    def test_harrison_county(self):
        self.assertTrue(is_north_central_context("Harrison County wreck"))

    def test_alias_mon_county(self):
        self.assertTrue(is_north_central_context("mon county road closure"))

    def test_city_morgantown(self):
        self.assertTrue(is_north_central_context("Crash near Morgantown on I-79"))

    def test_city_fairmont(self):
        self.assertTrue(is_north_central_context("I-79 wreck near Fairmont"))

    def test_city_bridgeport(self):
        self.assertTrue(is_north_central_context("Incident near Bridgeport"))

    def test_out_of_region(self):
        self.assertFalse(is_north_central_context("Kanawha County accident on I-77"))

    def test_empty_string(self):
        self.assertFalse(is_north_central_context(""))


# ---------------------------------------------------------------------------
# parse_wv511_i79_incidents
# ---------------------------------------------------------------------------

SAMPLE_WV511_LINES = [
    "I-79 Possible Delay",
    "Last Updated: 02/15/2025 10:30:00 AM",
    "County: Marion County",
    "Description: I-79 southbound lane closure near Fairmont due to crash.",
    "Comments: Use caution",
    "I-77 Some Other Event",
    "County: Kanawha County",
    "Description: I-77 construction.",
    "I-79 Road Work",
    "Last Updated: 02/15/2025 11:00:00 AM",
    "County: Monongalia County",
    "Description: I-79 lane closure for paving near Morgantown.",
]


class TestParseWv511Incidents(unittest.TestCase):

    def setUp(self):
        self.incidents = parse_wv511_i79_incidents(SAMPLE_WV511_LINES)

    def test_excludes_non_i79_events(self):
        sources = [i.source for i in self.incidents]
        self.assertTrue(all(s == "wv511.org" for s in sources))

    def test_excludes_out_of_region_county(self):
        # Kanawha County (I-77 event) should not appear
        titles = [i.title for i in self.incidents]
        self.assertFalse(any("I-77" in t for t in titles))

    def test_north_central_counties_included(self):
        counties = [i.location_text for i in self.incidents]
        self.assertTrue(len(counties) >= 1)

    def test_source_type_is_official(self):
        for incident in self.incidents:
            self.assertEqual(incident.source_type, "official_wv511")
            self.assertEqual(incident.verification_status, "official")

    def test_construction_tagged(self):
        construction = [i for i in self.incidents if i.construction_related]
        self.assertTrue(len(construction) >= 1)


# ---------------------------------------------------------------------------
# apply_manual_overrides
# ---------------------------------------------------------------------------

class TestApplyManualOverrides(unittest.TestCase):

    def _base_incident(self):
        return make_incident(
            id="aabbccddeeff",
            suspected_fatalities=0,
            verified_fatalities=None,
            verification_status="unverified",
            notes="",
        )

    def test_patches_verified_fatalities(self):
        incident = self._base_incident()
        payload = {
            "incident_overrides": {
                "aabbccddeeff": {"verified_fatalities": 2, "verification_status": "verified"}
            },
            "manual_incidents": [],
        }
        result = apply_manual_overrides([incident], payload)
        patched = next(i for i in result if i.id == "aabbccddeeff")
        self.assertEqual(patched.verified_fatalities, 2)
        self.assertEqual(patched.verification_status, "verified")

    def test_patches_notes(self):
        incident = self._base_incident()
        payload = {
            "incident_overrides": {"aabbccddeeff": {"notes": "Confirmed by WVSP"}},
            "manual_incidents": [],
        }
        result = apply_manual_overrides([incident], payload)
        patched = next(i for i in result if i.id == "aabbccddeeff")
        self.assertEqual(patched.notes, "Confirmed by WVSP")

    def test_unknown_id_is_ignored(self):
        incident = self._base_incident()
        payload = {
            "incident_overrides": {"000000000000": {"verified_fatalities": 5}},
            "manual_incidents": [],
        }
        result = apply_manual_overrides([incident], payload)
        patched = next(i for i in result if i.id == "aabbccddeeff")
        self.assertIsNone(patched.verified_fatalities)

    def test_adds_manual_incident(self):
        payload = {
            "incident_overrides": {},
            "manual_incidents": [
                {
                    "title": "Manual crash entry",
                    "url": "https://example.com/manual",
                    "source": "manual",
                    "published_at": "2025-01-01T00:00:00+00:00",
                    "summary": "Hand-entered.",
                    "construction_related": "false",
                    "suspected_fatalities": 1,
                    "verified_fatalities": 1,
                    "verification_status": "verified",
                }
            ],
        }
        result = apply_manual_overrides([], payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].title, "Manual crash entry")
        self.assertEqual(result[0].verified_fatalities, 1)

    def test_manual_incident_without_title_is_skipped(self):
        payload = {
            "incident_overrides": {},
            "manual_incidents": [{"title": "", "url": "https://example.com"}],
        }
        result = apply_manual_overrides([], payload)
        self.assertEqual(len(result), 0)

    def test_empty_overrides_returns_original(self):
        incident = self._base_incident()
        payload = {"incident_overrides": {}, "manual_incidents": []}
        result = apply_manual_overrides([incident], payload)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].id, "aabbccddeeff")


if __name__ == "__main__":
    unittest.main()
