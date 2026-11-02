"""Synthetic-only regressions for the private Eagle horizon audit."""

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schedule_horizon_audit import audit_horizons, parse_as_of


NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


class ScheduleHorizonAuditTest(unittest.TestCase):
    def _fixtures(self, root: Path, *, future_conflict=False):
        baseline = root / "baseline.xml"
        native = root / "native.xml"
        baseline.write_text('<tv><channel id="baseline" /></tv>', encoding="utf-8")
        events = [
            ('first.id', '20261102000000', '20261103000000', 'First day'),
            ('second.id', '20261102000000', '20261104000000', 'Two days'),
        ]
        if future_conflict:
            events.append(('second.id', '20261103120000', '20261104000000', 'Overlap'))
        programmes = ''.join(
            f'<programme channel="{channel}" start="{start} +0000" '
            f'stop="{stop} +0000"><title>{title}</title></programme>'
            for channel, start, stop, title in events
        )
        native.write_text(
            '<tv><channel id="first.id"/><channel id="second.id"/>'
            + programmes + '</tv>', encoding="utf-8"
        )
        playlist = [
            {"channel_id": "eagle.one", "name": "One", "stream_id": "1"},
            {"channel_id": "eagle.two", "name": "Two", "stream_id": "2"},
        ]
        catalog = {"1": {"epg_id": "first.id"}, "2": {"epg_id": "second.id"}}
        return playlist, catalog, baseline, native

    def test_24h_candidate_can_disappear_at_48h(self):
        with tempfile.TemporaryDirectory() as directory:
            playlist, catalog, baseline, native = self._fixtures(Path(directory))
            report = audit_horizons(
                playlist, catalog, baseline=baseline, eagle=native,
                as_of=NOW, hours=(12, 24, 36, 48),
            )
            self.assertEqual([r["candidate_channels"] for r in report["window_results"]],
                             [2, 2, 1, 1])
            self.assertEqual(report["window_results"][2]["rejection_counts"]
                             ["under_95pct_coverage"], 1)
            self.assertFalse(report["ready_to_replace_epg41"])
            self.assertNotIn("eagle.one", str(report))
            self.assertNotIn("First day", str(report))

    def test_long_window_overlaps_do_not_poison_short_window(self):
        with tempfile.TemporaryDirectory() as directory:
            playlist, catalog, baseline, native = self._fixtures(
                Path(directory), future_conflict=True,
            )
            report = audit_horizons(
                playlist, catalog, baseline=baseline, eagle=native,
                as_of=NOW, hours=(24, 48),
            )
            self.assertEqual(report["window_results"][0]["candidate_channels"], 2)
            self.assertEqual(report["window_results"][1]["candidate_channels"], 0)
            self.assertEqual(report["window_results"][1]["rejection_counts"]
                             ["source_schedule_overlap"], 1)

    def test_timestamp_and_horizon_validation(self):
        self.assertEqual(parse_as_of('2026-11-02T00:00:00Z'), NOW)
        self.assertEqual(parse_as_of('2026-11-01T19:00:00-05:00'), NOW)
        for raw in ('2026-11-02T00:00:00', 'nonsense'):
            with self.assertRaises(ValueError):
                parse_as_of(raw)
        with tempfile.TemporaryDirectory() as directory:
            playlist, catalog, baseline, native = self._fixtures(Path(directory))
            for hours in ((), (24, 24), (48, 24), (0, 12), (49,)):
                with self.assertRaises(ValueError):
                    audit_horizons(
                        playlist, catalog, baseline=baseline, eagle=native,
                        as_of=NOW, hours=hours,
                    )


if __name__ == '__main__':
    unittest.main()
