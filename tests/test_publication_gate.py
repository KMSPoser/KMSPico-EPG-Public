import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from epg_public import build
from publication_gate import check_publication


NOW = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)


class PublicationGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "verified_events.json"
        self.docs = self.root / "docs"

    def build_with(self, events):
        self.config.write_text(json.dumps({"version": 1, "events": events}), encoding="utf-8")
        return build(self.config, self.docs, NOW)

    def check(self):
        return check_publication(self.docs / "guide.xml", self.docs / "coverage.json")

    @staticmethod
    def sample():
        return {
            "channel_id": "cw8.us", "channel_name": "Example Channel",
            "title": "Verified programme",
            "start_utc": "2026-11-09T21:00:00Z", "stop_utc": "2026-11-09T22:00:00Z",
            "verified_source_url": "https://example.org/schedule",
        }

    def test_empty_is_valid_but_explicitly_unready(self):
        self.build_with([])
        report = self.check()
        self.assertEqual(report["status"], "empty_awaiting_verified_sources")
        self.assertEqual(report["programmes"], 0)

    def test_only_original_operator_verified_guide_passes(self):
        self.build_with([self.sample()])
        self.assertEqual(self.check()["status"], "supplement_populated")

    def test_copied_provider_guide_is_rejected(self):
        self.build_with([self.sample()])
        tree = ET.parse(self.docs / "guide.xml")
        tree.getroot().attrib["generator-info-name"] = "Eagle native EPG"
        tree.write(self.docs / "guide.xml", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not_original_verified_supplement"):
            self.check()

    def test_credential_like_title_is_rejected_before_publication(self):
        self.build_with([self.sample() | {"title": "https://provider.example/get.php?username=oops"}])
        with self.assertRaisesRegex(ValueError, "credential_like_public_programme"):
            self.check()

    def test_report_count_mismatch_is_rejected(self):
        self.build_with([self.sample()])
        report_file = self.docs / "coverage.json"
        report = json.loads(report_file.read_text(encoding="utf-8"))
        report["programmes"] = 42
        report_file.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "public_counts_do_not_match"):
            self.check()

    def test_orphan_programme_rejected(self):
        self.build_with([self.sample()])
        guide_file = self.docs / "guide.xml"
        tree = ET.parse(guide_file)
        tree.getroot().find("programme").attrib["channel"] = "other.us"
        tree.write(guide_file, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "orphan_public_programme"):
            self.check()


if __name__ == "__main__":
    unittest.main()
