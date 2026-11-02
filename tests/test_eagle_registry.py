import json
from pathlib import Path
import tempfile
import unittest

from catalog_audit import parse_playlist
from eagle_registry import registry_from_entries, write_private_registry


PLAYLIST = '''#EXTM3U
#EXTINF:-1 tvg-id="ESPN.us" group-title="Sports",ESPN
https://username:secret@example.invalid/live/666.m3u8
#EXTINF:-1 tvg-id="espn.us" group-title="Backups",ESPN Backup
https://username:secret@example.invalid/live/667.m3u8
#EXTINF:-1 tvg-id="CNN.us" group-title="News",CNN
https://username:secret@example.invalid/live/668.m3u8
#EXTINF:-1 tvg-id="dummy-event-01" group-title="NHL",Event 01
https://username:secret@example.invalid/live/669.m3u8
#EXTINF:-1 tvg-id="" group-title="NHL",Event 02
https://username:secret@example.invalid/live/670.m3u8
'''


class EagleRegistryTests(unittest.TestCase):
    def test_exact_match_not_identity_and_duplicate_ids_not_rewritten(self):
        data = registry_from_entries(parse_playlist(PLAYLIST),
                                     ["ESPN.us", "CNN.US"],
                                     created_utc="2026-11-02T12:00:00Z")
        stats = data["summary"]
        self.assertEqual(stats["channel_entries"], 5)
        self.assertEqual(stats["distinct_real_tvg_ids"], 2)
        self.assertEqual(stats["shared_real_tvg_ids"], 1)
        self.assertEqual(stats["entries_with_shared_real_tvg_id"], 2)
        self.assertEqual(stats["epg_status_counts"], {
            "baseline_exact_match": 1,
            "baseline_no_exact_match": 2,
            "placeholder_or_missing": 2,
        })
        self.assertEqual(data["channels"][0]["tvg_id"], "ESPN.us")
        self.assertEqual(data["channels"][1]["tvg_id"], "espn.us")
        self.assertEqual(data["channels"][0]["shared_id_entries"], 2)
        self.assertEqual(data["channels"][1]["shared_id_entries"], 2)
        self.assertTrue(all(row["network_identity"] == "unverified" for row in data["channels"]))
        self.assertTrue(all(not row["approved_for_public_guide"] for row in data["channels"]))
        self.assertFalse(stats["ready_to_replace_existing_epg"])

    def test_never_serializes_passwords_urls_or_stream_ids(self):
        data = registry_from_entries(parse_playlist(PLAYLIST), ["ESPN.us"])
        serialized = json.dumps(data)
        for sensitive in ("username", "secret", "example.invalid", '"stream_id":', "666"):
            self.assertNotIn(sensitive, serialized)

    def test_missing_baseline_does_not_mean_guide_is_unmatched(self):
        data = registry_from_entries(parse_playlist(PLAYLIST))
        self.assertFalse(data["summary"]["baseline_checked"])
        self.assertEqual(data["summary"]["epg_status_counts"]["baseline_not_evaluated"], 3)

    def test_refuse_output_inside_public_repo(self):
        location = Path(__file__).resolve().parents[1] / "private" / "registry.json"
        with self.assertRaisesRegex(ValueError, "outside the public repository"):
            write_private_registry(location, {"not": "written"})
        self.assertFalse(location.exists())

    def test_create_private_file_without_stream_urls(self):
        data = registry_from_entries(parse_playlist(PLAYLIST), ["CNN.us"])
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "Eagle_Channel_Registry.json"
            write_private_registry(destination, data)
            self.assertEqual(json.loads(destination.read_text())["summary"]["channel_entries"], 5)
            self.assertNotIn("secret", destination.read_text())


if __name__ == "__main__":
    unittest.main()
