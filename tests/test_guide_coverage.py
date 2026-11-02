import gzip
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from catalog_audit import parse_playlist
from guide_coverage import candidate_pairs, coverage_report, parse_xmltv_time


PLAYLIST = '''#EXTM3U
#EXTINF:-1 tvg-id="espn.us",ESPN
https://example.invalid/not-a-real-stream.m3u8
#EXTINF:-1 tvg-id="cnn.us",CNN
https://example.invalid/not-a-real-stream2.m3u8
'''
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


class GuideCoverageTests(unittest.TestCase):
    def test_xmltv_timezone_required_and_converted_to_utc(self):
        self.assertEqual(parse_xmltv_time("20261102080000 -0400"), NOW)
        self.assertIsNone(parse_xmltv_time("20261102080000"))
        self.assertIsNone(parse_xmltv_time("20261102990000 +0000"))

    def test_mappings_are_only_candidates(self):
        exact, case_only = candidate_pairs(parse_playlist(PLAYLIST), ["ESPN.us", "cnn.us"])
        self.assertEqual(exact, {"cnn.us"})
        self.assertEqual(case_only, {"espn.us": "ESPN.us"})
        exact, case_only = candidate_pairs(parse_playlist(PLAYLIST),
                                           ["ESPN.us", "Espn.us", "cnn.us"])
        self.assertEqual(case_only, {})

    def test_window_counts_valid_programmes_and_merges_overlaps(self):
        source = b'''<?xml version="1.0"?><tv>
<channel id="ESPN.us"/><channel id="cnn.us"/>
<programme channel="ESPN.us" start="20261102120000 +0000" stop="20261103120000 +0000"/>
<programme channel="ESPN.us" start="20261103060000 +0000" stop="20261103180000 +0000"/>
<programme channel="ESPN.us" start="20261101000000 +0000" stop="20261101010000 +0000"/>
<programme channel="cnn.us" start="20261103000000 +0000" stop="20261103010000 +0000"/>
<programme channel="cnn.us" start="bad" stop="bad"/>
</tv>'''
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "guide.xml.gz"
            source_path.write_bytes(gzip.compress(source))
            report = coverage_report(parse_playlist(PLAYLIST), source_path, now=NOW)
        self.assertEqual(report["exact_ids_with_programmes_in_window"], 1)
        self.assertEqual(report["case_only_ids_with_programmes_in_window"], 1)
        self.assertEqual(report["case_only_ids_with_at_least_24h_coverage"], 1)
        self.assertEqual(report["median_case_only_hours_covered"], 30)
        self.assertEqual(report["programmes_for_exact_ids_in_window"], 1)
        self.assertEqual(report["programmes_for_case_only_ids_in_window"], 2)
        self.assertEqual(report["invalid_timestamps_in_matched_programmes"], 1)
        self.assertTrue(report["guide_programme_titles_not_recorded"])
        self.assertFalse(report["ready_to_replace_existing_epg"])
        self.assertNotIn("example.invalid", str(report))

    def test_stale_schedule_has_no_future_coverage(self):
        source = b'''<tv><channel id="ESPN.us"/>
<programme channel="ESPN.us" start="20261001000000 +0000" stop="20261001010000 +0000"/>
</tv>'''
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "guide.xml"
            source_path.write_bytes(source)
            report = coverage_report(parse_playlist(PLAYLIST), source_path, now=NOW)
        self.assertEqual(report["case_only_candidates_not_automatically_assigned"], 1)
        self.assertEqual(report["case_only_ids_with_programmes_in_window"], 0)
        self.assertEqual(report["median_case_only_hours_covered"], 0)

    def test_window_must_be_bounded(self):
        with self.assertRaisesRegex(ValueError, "Window must be"):
            coverage_report(parse_playlist(PLAYLIST), Path("unused.xml"), now=NOW, hours=0)


if __name__ == "__main__":
    unittest.main()
