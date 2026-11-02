"""Offline tests for private, non-publishing pilot coverage review."""

from datetime import datetime, timezone
import json
import unittest

from pilot_schedule_audit import pilot_schedule_report


class PilotScheduleAuditTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
        self.playlist = [{"name": "HGTV", "channel_id": "hgtv.us",
                          "group": "Home", "stream_id": "123"}]
        self.catalog = {"123": {"name": "US HGTV", "epg_id": "hgtv.us"}}

    def _episode(self, start="2026-11-02T13:00:00Z", runtime=60, network=192):
        return {"airstamp": start, "runtime": runtime,
                "url": "https://www.tvmaze.com/episodes/1/example",
                "name": "Never publish me", "show": {
                    "name": "Secret show", "network": {"id": network, "name": "HGTV"}}}

    def test_deduplicates_intervals_and_never_promotes_candidate(self):
        first = self._episode()
        next_ = self._episode("2026-11-02T13:30:00Z", 60)
        report = pilot_schedule_report(self.playlist, self.catalog,
                                       [[first, next_], [first]], now=self.now)
        self.assertEqual(report["summary"]["candidates_with_source_identity_hints"], 1)
        item = report["candidates"][0]
        self.assertEqual(item["episode_intervals_in_window"], 2)
        self.assertEqual(item["hours_covered"], 1.5)
        self.assertEqual(item["longest_uncovered_gap_hours"], 45.5)
        self.assertFalse(item["actual_stream_verified"])
        self.assertFalse(report["summary"]["ready_to_replace_epg41"])
        self.assertNotIn("Never publish me", json.dumps(report))
        self.assertNotIn("Secret show", json.dumps(report))
        self.assertNotIn("123", json.dumps(report))

    def test_unmatched_network_gives_zero_coverage(self):
        unrelated = self._episode(network=99)
        unrelated["show"]["network"]["name"] = "Other Network"
        report = pilot_schedule_report(self.playlist, self.catalog,
                                       [[unrelated]], now=self.now)
        item = report["candidates"][0]
        self.assertEqual(item["tvmaze_discovery_status"], "not_found_in_sample")
        self.assertEqual(item["hours_covered"], 0)
        self.assertEqual(item["longest_uncovered_gap_hours"], 48)

    def test_ignores_malformed_episode_times(self):
        episode = self._episode()
        bad = self._episode("invalid", 60)
        report = pilot_schedule_report(self.playlist, self.catalog,
                                       [[episode, bad]], now=self.now)
        self.assertEqual(report["candidates"][0]["hours_covered"], 1)

    def test_only_counts_episodes_the_importer_could_use(self):
        valid = self._episode()
        bad_url = self._episode("2026-11-02T15:00:00Z")
        bad_url["url"] = "https://somewhere.invalid/episodes/2"
        bad_show = self._episode("2026-11-02T16:00:00Z")
        bad_show["show"]["name"] = ""
        report = pilot_schedule_report(self.playlist, self.catalog,
                                       [[valid, bad_url, bad_show]], now=self.now)
        self.assertEqual(report["candidates"][0]["episode_intervals_in_window"], 1)

    def test_rejects_invalid_windows_and_naive_now(self):
        for hours in (0, 169):
            with self.assertRaises(ValueError):
                pilot_schedule_report(self.playlist, self.catalog, [[]],
                                      now=self.now, window_hours=hours)
        with self.assertRaises(ValueError):
            pilot_schedule_report(self.playlist, self.catalog, [[]],
                                  now=self.now.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            pilot_schedule_report(self.playlist, self.catalog, [], now=self.now)

    def test_reused_id_is_not_pilot_candidate(self):
        playlist = self.playlist + [{"name": "HGTV backup", "channel_id": "hgtv.us",
                                     "group": "Home", "stream_id": "234"}]
        report = pilot_schedule_report(playlist, self.catalog,
                                       [[self._episode()]], now=self.now)
        self.assertEqual(report["summary"]["pilot_candidates"], 0)


if __name__ == "__main__":
    unittest.main()
