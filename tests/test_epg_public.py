import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from epg_public import build, validated_events


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

    def test_expired_event_omitted(self):
        old = event(start_utc="2026-10-28T21:00:00Z", stop_utc="2026-10-28T23:00:00Z")
        self.assertEqual(validated_events({"version": 1, "events": [old]}, NOW), [])

    def test_overlap_rejected(self):
        second = event(title="Other", start_utc="2026-10-30T22:00:00Z", stop_utc="2026-10-30T23:30:00Z")
        with self.assertRaises(ValueError):
            validated_events({"version": 1, "events": [event(), second]}, NOW)


if __name__ == "__main__":
    unittest.main()
