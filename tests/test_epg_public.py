import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from epg_public import build, make_guide, validated_events
from tvmaze_source import channel_mappings, events_from_schedule, load_tvmaze_events


NOW = datetime(2026, 10, 30, 20, 0, tzinfo=timezone.utc)


def event(**updates):
    base = {
        "channel_id": "example.us", "channel_name": "Example",
        "title": "Verified event", "start_utc": "2026-10-30T21:00:00Z",
        "stop_utc": "2026-10-30T23:00:00Z",
        "verified_source_url": "https://example.org/schedule",
    }
    return {**base, **updates}


class GuideTests(unittest.TestCase):
    def test_empty_guide_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "events.json"
            config.write_text('{"version":1,"events":[]}', encoding="utf-8")
            result = build(config, root / "docs", NOW)
            self.assertEqual(result["programmes"], 0)
            self.assertEqual(ET.parse(root / "docs" / "guide.xml").getroot().tag, "tv")

    def test_verified_programme_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "events.json"
            config.write_text(json.dumps({"version": 1, "events": [event()]}), encoding="utf-8")
            report = build(config, root / "docs", NOW)
            self.assertEqual(report["programmes"], 1)
            programme = ET.parse(root / "docs" / "guide.xml").getroot().find("programme")
            self.assertEqual(programme.findtext("title"), "Verified event")
            self.assertEqual(programme.get("start"), "20261030210000 +0000")

    def test_rejects_credentials_in_verification_url(self):
        with self.assertRaises(ValueError):
            validated_events({"version": 1, "events": [event(verified_source_url="https://me:pw@example.org/")]}, NOW)

    def test_rejects_credentials_in_query_and_stream_links(self):
        for url in ("https://example.org/schedule?password=123",
                    "https://example.org/schedule?access_token=123",
                    "https://example.org/live/123.m3u8"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validated_events({"version": 1, "events": [event(verified_source_url=url)]}, NOW)

    def test_expired_event_omitted(self):
        old = event(start_utc="2026-10-28T21:00:00Z", stop_utc="2026-10-28T23:00:00Z")
        self.assertEqual(validated_events({"version": 1, "events": [old]}, NOW), [])

    def test_overlap_rejected(self):
        second = event(title="Other", start_utc="2026-10-30T22:00:00Z", stop_utc="2026-10-30T23:30:00Z")
        with self.assertRaises(ValueError):
            validated_events({"version": 1, "events": [event(), second]}, NOW)


MAPPING = {
    "channel_id": "example.us", "channel_name": "Example Channel",
    "tvmaze_network_id": 40, "tvmaze_network_name": "CNN",
    "kind": "network", "operator_verified": True,
}


class TvmazeTests(unittest.TestCase):
    def test_mapping_requires_operator_confirmation(self):
        with self.assertRaises(ValueError):
            channel_mappings({"version": 1, "channels": [{**MAPPING, "operator_verified": False}]})

    def test_network_name_mismatch_never_publishes(self):
        episode = self.sample_episode()
        episode["show"]["network"]["name"] = "Other Network"
        self.assertEqual(events_from_schedule([episode], [MAPPING]), [])

    def test_import_uses_existing_channel_id_and_source_attribution(self):
        events = events_from_schedule([self.sample_episode()], channel_mappings({"version": 1, "channels": [MAPPING]}))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["channel_id"], "example.us")
        self.assertEqual(events[0]["start_utc"], "2026-10-30T21:00:00Z")
        self.assertEqual(events[0]["stop_utc"], "2026-10-30T22:00:00Z")
        self.assertEqual(events[0]["source"], "tvmaze")
        validated = validated_events({"version": 1, "events": events}, NOW)
        programme = make_guide(validated).find("programme")
        self.assertIn("TVmaze (CC BY-SA 4.0)", programme.findtext("desc"))

    def test_empty_mapping_never_calls_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "tvmaze.json"
            config.write_text('{"version":1,"channels":[]}', encoding="utf-8")
            result = load_tvmaze_events(config, NOW, lambda _: self.fail("API unexpectedly called"))
            self.assertEqual(result, [])

    def test_build_merges_tvmaze_and_manual_entries_without_playlist_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = root / "manual.json"
            auto = root / "tvmaze.json"
            manual.write_text('{"version":1,"events":[]}', encoding="utf-8")
            auto.write_text(json.dumps({"version": 1, "channels": []}), encoding="utf-8")
            report = build(manual, root / "docs", NOW, auto)
            self.assertEqual(report["tvmaze_programmes"], 0)
            self.assertEqual(report["programmes"], 0)

    @staticmethod
    def sample_episode():
        return {
            "airstamp": "2026-10-30T17:00:00-04:00", "runtime": 60,
            "name": "Tonight", "url": "https://www.tvmaze.com/episodes/1234/example",
            "show": {"name": "Example Show", "network": {"id": 40, "name": "CNN"}},
        }


if __name__ == "__main__":
    unittest.main()
