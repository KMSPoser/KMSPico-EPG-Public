"""Synthetic, privacy-safe tests for XMLTV collision classification."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_conflict_audit import audit, canonical_title, classify


NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


class SourceConflictAuditTest(unittest.TestCase):
    def test_unicode_case_and_spacing_are_trivial(self):
        self.assertEqual(canonical_title("  MOVIE   Night  "), "movie night")
        self.assertEqual(classify({"Movie Night", " movie   night "}),
                         "case_or_spacing_only")

    def test_punctuation_only_difference_is_trivial(self):
        self.assertEqual(classify({"Sports: Tonight", "Sports Tonight"}),
                         "punctuation_only")

    def test_generic_placeholders_are_explicitly_classified(self):
        self.assertEqual(classify({"No Information", "TBA"}), "only_placeholders")
        self.assertEqual(classify({"No Information", "Actual Show"}),
                         "placeholder_and_real_title")

    def test_distinct_credible_titles_are_substantive(self):
        self.assertEqual(classify({"Evening News", "Football Game"}),
                         "substantive_title_conflict")
        self.assertEqual(classify({"The Show"}), "not_a_conflict")

    def test_audit_only_reports_aggregates(self):
        slots = (
            '<programme channel="sample.private" start="20261102000000 +0000" '
            'stop="20261102020000 +0000"><title>News</title></programme>'
            '<programme channel="sample.private" start="20261102000000 +0000" '
            'stop="20261102020000 +0000"><title>Sports</title></programme>'
            '<programme channel="other" start="20261102000000 +0000" '
            'stop="20261102020000 +0000"><title>Do Not Include</title></programme>'
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "guide.xml"
            path.write_text('<tv><channel id="sample.private"/>' + slots + '</tv>',
                            encoding="utf-8")
            result = audit(path, {"sample.private"}, begin=NOW, end=NOW + timedelta(hours=24))
        self.assertEqual(result["source_ids_with_any_collision"], 1)
        self.assertEqual(result["collisions_by_type"]["substantive_title_conflict"], 1)
        serialized = json.dumps(result)
        for private_value in ("News", "Sports", "sample.private", "Do Not Include"):
            self.assertNotIn(private_value, serialized)
        self.assertFalse(result["automatic_conflict_resolution_approved"])


if __name__ == "__main__":
    unittest.main()
