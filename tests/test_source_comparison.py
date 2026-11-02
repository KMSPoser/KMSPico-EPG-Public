import gzip
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from catalog_audit import parse_playlist
from source_comparison import (compare_sources, interval_metrics, parse_candidate,
                               scan_xmltv)


NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
PLAYLIST = '''#EXTM3U
#EXTINF:-1 tvg-id="espn.us",ESPN
https://user:secret@example.invalid/1234.m3u8
#EXTINF:-1 tvg-id="cnn.us",CNN
https://user:secret@example.invalid/2345.m3u8
#EXTINF:-1 tvg-id="cnn.us",CNN Backup
https://user:secret@example.invalid/3456.m3u8
#EXTINF:-1 tvg-id="dummy-event",Sports Event
https://user:secret@example.invalid/4567.m3u8
'''


def xmltv(*children):
    return ("<tv>" + "".join(children) + "</tv>").encode()


def programme(channel, start, stop, title="private sports show"):
    return (f'<programme channel="{channel}" start="{start}" stop="{stop}">'
            f'<title>{title}</title></programme>')


class SourceComparisonTests(unittest.TestCase):
    def test_compare_exact_coverage_and_case_only_without_publishing(self):
        first = xmltv(
            '<channel id="espn.us"/><channel id="cnn.us"/>',
            programme("espn.us", "20261102120000 +0000", "20261103120000 +0000"),
            programme("espn.us", "20261103000000 +0000", "20261104120000 +0000"),
            programme("cnn.us", "20261103000000 +0000", "20261103010000 +0000"),
            programme("cnn.us", "bad", "bad"),
        )
        second = xmltv(
            '<channel id="ESPN.us"/><channel id="cnn.us"/>',
            programme("ESPN.us", "20261102120000 +0000", "20261104120000 +0000"),
        )
        with tempfile.TemporaryDirectory() as directory:
            a = Path(directory) / "first.xml"
            b = Path(directory) / "second.xml.gz"
            a.write_bytes(first)
            b.write_bytes(gzip.compress(second))
            report = compare_sources(parse_playlist(PLAYLIST),
                                     [("provider_a", a), ("provider_b", b)], now=NOW)
            self.assertEqual(a.read_bytes(), first)
            self.assertEqual(b.read_bytes(), gzip.compress(second))
        self.assertEqual(report["main_playlist_entries"], 4)
        self.assertEqual(report["distinct_nonplaceholder_main_ids"], 2)
        self.assertEqual(report["unique_exact_ids_found_in_any_source"], 2)
        self.assertEqual(report["source_summaries"][0]["exact_main_id_matches"], 2)
        self.assertEqual(report["source_summaries"][0]["invalid_timestamps_for_candidate_main_ids"], 1)
        self.assertEqual(report["source_summaries"][0]["unique_main_ids_with_exact_95pct_schedule_coverage"], 1)
        self.assertEqual(report["source_summaries"][1]["case_only_manual_mapping_candidates"], 1)
        by_id = {row["tvg_id"]: row for row in report["channels"]}
        espn = by_id["espn.us"]["candidate_sources"]
        self.assertEqual(espn[0]["window_coverage_percent"], 100)
        self.assertEqual(espn[0]["longest_uncovered_hours"], 0)
        self.assertEqual(espn[0]["future_programme_count"], 2)
        self.assertEqual(espn[1]["id_match"], "case_only_manual_mapping_required")
        self.assertEqual(espn[1]["window_coverage_percent"], 100)
        self.assertEqual(by_id["cnn.us"]["playlist_entries"], 2)
        self.assertTrue(by_id["cnn.us"]["shared_id"])
        self.assertEqual(by_id["cnn.us"]["candidate_sources"][0]["longest_uncovered_hours"], 35)
        self.assertFalse(report["ready_to_replace_existing_epg"])
        self.assertEqual(report["stream_identities_approved"], 0)
        self.assertEqual(report["sources_authorized_for_redistribution"], 0)
        serialized = str(report)
        for forbidden in ("secret", "example.invalid", "1234", "private sports show", "dummy-event"):
            self.assertNotIn(forbidden, serialized)

    def test_coverage_merges_overlaps_and_counts_gaps(self):
        from datetime import timedelta
        end = NOW + timedelta(hours=4)
        intervals = [(NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
                     (NOW + timedelta(hours=1, minutes=30), NOW + timedelta(hours=3))]
        fraction, gap = interval_metrics(intervals, begin=NOW, end=end)
        self.assertEqual((fraction, gap), (0.5, 1.0))
        self.assertEqual(interval_metrics([], begin=NOW, end=end), (0, 4))

    def test_ambiguous_casefold_does_not_choose_source_channel(self):
        source = xmltv('<channel id="ESPN.US"/><channel id="ESPN.us"/>',
                       programme("ESPN.US", "20261102120000 +0000", "20261104120000 +0000"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.xml"
            path.write_bytes(source)
            report = compare_sources(parse_playlist(PLAYLIST), [("local", path)], now=NOW)
        candidate = next(c for c in report["channels"] if c["tvg_id"] == "espn.us")
        self.assertEqual(candidate["candidate_sources"][0]["id_match"], "ambiguous_casefold")
        self.assertEqual(candidate["candidate_sources"][0]["future_programme_count"], 0)
        self.assertEqual(report["source_summaries"][0]["ambiguous_casefold_matches"], 1)

    def test_undeclared_programmes_do_not_count_as_exact_id_match(self):
        source = xmltv(programme("espn.us", "20261102120000 +0000", "20261104120000 +0000"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-declaration.xml"
            path.write_bytes(source)
            report = compare_sources(parse_playlist(PLAYLIST), [("source", path)], now=NOW)
        self.assertEqual(report["unique_exact_ids_found_in_any_source"], 0)
        self.assertTrue(all(not c["candidate_sources"] for c in report["channels"]))

    def test_xmltv_requires_valid_root_and_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.xml"
            path.write_text('<invalid><channel id="espn.us"/></invalid>', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "XMLTV"):
                scan_xmltv(path, {"espn.us"}, begin=NOW, end=NOW.replace(day=4))

    def test_bad_labels_and_invalid_windows_are_refused(self):
        for invalid in ("missing", "=file.xml", "space name=file.xml", "source=", "/tmp=foo"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_candidate(invalid)
        self.assertEqual(parse_candidate("source=/tmp/test.xml"), ("source", Path("/tmp/test.xml")))
        playlist = parse_playlist(PLAYLIST)
        for candidate_list, hours, now in (([], 48, NOW),
                                           ([("x", Path("any.xml"))], 0, NOW),
                                           ([("x", Path("any.xml"))], 48, NOW.replace(tzinfo=None)),
                                           ([("x", Path("a")), ("x", Path("b"))], 48, NOW)):
            with self.assertRaises(ValueError):
                compare_sources(playlist, candidate_list, now=now, hours=hours)


if __name__ == "__main__":
    unittest.main()
