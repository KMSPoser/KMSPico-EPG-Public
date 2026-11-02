"""Synthetic, private-safe preflight tests."""

import gzip
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from name_crosswalk import guide_names, normalize_name, summarize


class CrosswalkTest(unittest.TestCase):
    def test_normalization_is_conservative(self):
        self.assertEqual(normalize_name("  A & E  HD "), "a e hd")
        self.assertEqual(normalize_name("  A & E  HD ", quality=True), "a e")
        self.assertNotEqual(normalize_name("A and E"), normalize_name("A&E"))

    def test_exact_name_requires_single_guide_id(self):
        playlist = [{"channel_id": "eagle.custom", "name": "News One"}]
        report = summarize(playlist, {"news.us": {"News One"}})
        self.assertEqual(report["single_exact_name_hint"], 1)
        self.assertEqual(report["approved_mappings"], 0)

    def test_ambiguity_is_not_auto_resolved(self):
        playlist = [{"channel_id": "eagle.custom", "name": "News One"}]
        report = summarize(playlist, {"east.us": {"News One"}, "west.us": {"News One"}})
        self.assertEqual(report["ambiguous_exact_name_hints"], 1)
        self.assertEqual(report["single_exact_name_hint"], 0)

    def test_quality_only_hint_is_separate(self):
        playlist = [{"channel_id": "eagle.custom", "name": "News One FHD"}]
        report = summarize(playlist, {"news.us": {"News One"}})
        self.assertEqual(report["single_quality_suffix_hint"], 1)

    def test_duplicate_eagle_id_conflict_is_ambiguous(self):
        playlist = [
            {"channel_id": "one.eagle", "name": "News One"},
            {"channel_id": "one.eagle", "name": "News Two"},
        ]
        report = summarize(playlist, {"one.us": {"News One"}, "two.us": {"News Two"}})
        self.assertEqual(report["eagle_distinct_nonplaceholder_ids"], 1)
        self.assertEqual(report["ambiguous_exact_name_hints"], 1)

    def test_placeholder_exclusion_and_existing_id(self):
        playlist = [
            {"channel_id": "dummy-01", "name": "Event"},
            {"channel_id": "news.us", "name": "Wrong Label"},
        ]
        report = summarize(playlist, {"news.us": {"News One"}})
        self.assertEqual(report["eagle_distinct_nonplaceholder_ids"], 1)
        self.assertEqual(report["existing_exact_id"], 1)

    def test_gzip_reads_only_channel_aliases(self):
        xml = (b'<tv><channel id="news.us"><display-name>News One</display-name>'
               b'</channel><programme channel="news.us" start="bad">'
               b'<title>Private Title</title></programme></tv>')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "guide.xml.gz"
            with gzip.open(path, "wb") as handle:
                handle.write(xml)
            self.assertEqual(guide_names(path), {"news.us": {"News One"}})


if __name__ == "__main__":
    unittest.main()
