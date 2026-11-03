"""Synthetic-only checks for private Eagle snapshot refresh comparisons."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schedule_refresh_audit import compare_snapshots


NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


class ScheduleRefreshAuditTest(unittest.TestCase):
    def _fixtures(self, directory: Path):
        baseline = directory / "baseline.xml"
        older = directory / "earlier.xml"
        newer = directory / "fresh.xml"
        baseline.write_text('<tv><channel id="other"/></tv>', encoding="utf-8")

        def guide(first_stop):
            return (
                '<tv><channel id="first.src"/><channel id="second.src"/>'
                '<programme channel="first.src" start="20261102000000 +0000" '
                f'stop="{first_stop} +0000"><title>Private first title</title></programme>'
                '<programme channel="second.src" start="20261102000000 +0000" '
                'stop="20261104000000 +0000"><title>Private second title</title>'
                '</programme></tv>'
            )

        older.write_text(guide("20261102120000"), encoding="utf-8")
        newer.write_text(guide("20261103000000"), encoding="utf-8")
        playlist = [
            {"channel_id": "eagle.one", "name": "One", "stream_id": "1"},
            {"channel_id": "eagle.two", "name": "Two", "stream_id": "2"},
        ]
        catalog = {"1": {"epg_id": "first.src"},
                   "2": {"epg_id": "second.src"}}
        return playlist, catalog, baseline, older, newer

    def test_refresh_adds_24_hour_candidate_without_changing_48_hour_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._fixtures(Path(tmp))
            report = compare_snapshots(
                args[0], args[1], baseline=args[2], older=args[3],
                newer=args[4], as_of=NOW, hours=(6, 24, 48),
            )
            self.assertEqual(
                [r["candidate_channel_change"] for r in report["window_results"]],
                [0, 1, 0],
            )
            self.assertEqual(report["window_results"][-1]["fresh_candidate_channels"], 1)
            self.assertFalse(report["ready_to_replace_epg41"])
            self.assertFalse(report["snapshots_binary_identical"])

    def test_private_identifiers_and_programme_names_do_not_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._fixtures(Path(tmp))
            report = compare_snapshots(
                args[0], args[1], baseline=args[2], older=args[3],
                newer=args[4], as_of=NOW, hours=(24,),
            )
            report_text = str(report)
            for private_detail in ("eagle.one", "first.src", "Private first title",
                                   "earlier.xml", "fresh.xml", str(tmp)):
                self.assertNotIn(private_detail, report_text)
            self.assertFalse(report["approved_for_public_guide"])

    def test_reject_same_file_and_identify_equivalent_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._fixtures(Path(tmp))
            with self.assertRaises(ValueError):
                compare_snapshots(
                    args[0], args[1], baseline=args[2], older=args[3],
                    newer=args[3], as_of=NOW, hours=(24,),
                )
            args[4].write_bytes(args[3].read_bytes())
            report = compare_snapshots(
                args[0], args[1], baseline=args[2], older=args[3],
                newer=args[4], as_of=NOW, hours=(24,),
            )
            self.assertTrue(report["snapshots_binary_identical"])
            self.assertEqual(report["window_results"][0]["candidate_channel_change"], 0)


if __name__ == "__main__":
    unittest.main()
