import json
import unittest

from catalog_audit import annotate_nhl_schedule, audit, index_catalog, numeric_stream_id, parse_playlist


M3U = '''#EXTM3U url-tvg="https://example.com/guide.xml"
#EXTINF:-1 tvg-id="cw8kpax.us" group-title="Local, CW",Missoula | CW
https://provider.example/live/secret-username/secret-password/278751.m3u8
#EXTINF:-1 tvg-id="dummy-4956" group-title="Sports",NHL Event 01
https://provider.example/live/secret-username/secret-password/303166.m3u8
'''.replace("\n#EXTINF", "\n#EXTINF")

CATALOG = json.dumps([
    {"stream_id": 278751, "name": "|US| CW 8 [MISSOULA]", "epg_channel_id": "cw8kpax.us",
     "direct_source": "https://private.example?password=top-secret"},
    {"stream_id": 303166, "name": "NHL | 01 - 1pm Jets @ Hurricanes", "epg_channel_id": ""},
])


class CatalogAuditTests(unittest.TestCase):
    def test_extracts_stream_id_without_retaining_url_or_secrets(self):
        entries = parse_playlist(M3U)
        self.assertEqual([e["stream_id"] for e in entries], ["278751", "303166"])
        self.assertEqual(entries[0]["group"], "Local, CW")
        self.assertEqual(entries[0]["name"], "Missoula | CW")
        self.assertNotIn("secret-password", json.dumps(entries))

    def test_allows_only_numeric_stream_id_at_end_of_url(self):
        self.assertIsNone(numeric_stream_id("https://provider.example/hls/master.m3u8"))
        self.assertIsNone(numeric_stream_id("file:///media/278751.m3u8"))
        self.assertEqual(numeric_stream_id("https://private.example/u/p/278751.ts?token=hidden"), "278751")

    def test_audit_preserves_playlist_epg_ids_and_flags_sports_candidates(self):
        entries = parse_playlist(M3U)
        report = audit(entries, index_catalog(CATALOG))
        self.assertEqual(report["counts"]["provider_stream_id_matched"], 2)
        self.assertEqual(report["counts"]["epg_ids_agree"], 1)
        self.assertEqual(report["counts"]["placeholder_epg_id"], 1)
        self.assertEqual(report["counts"]["provider_epg_id_missing"], 1)
        dynamic = report["nhl_event_candidates"][0]
        self.assertEqual(dynamic["channel_id"], "dummy-4956")
        self.assertEqual(dynamic["provider_label_hint"], "1pm Jets @ Hurricanes")
        self.assertFalse(dynamic["publishable_as_epg"])

    def test_report_never_includes_stream_urls_or_credentials(self):
        report = audit(parse_playlist(M3U), index_catalog(CATALOG))
        text = json.dumps(report)
        for secret in ("provider.example", "secret-username", "secret-password", "top-secret"):
            self.assertNotIn(secret, text)

    def test_conflicting_catalog_stream_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            index_catalog('[{"stream_id":5},{"stream_id":5}]')

    def test_dynamic_slot_mismatch_does_not_invent_a_game(self):
        entries = parse_playlist(M3U)
        catalog = index_catalog(json.dumps([
            {"stream_id": 303166, "name": "NHL | 02 - Different Game", "epg_channel_id": ""},
        ]))
        dynamic = audit(entries, catalog)["nhl_event_candidates"][0]
        self.assertEqual(dynamic["provider_label_hint"], "")
        self.assertFalse(dynamic["publishable_as_epg"])

    def test_official_nhl_schedule_matches_et_start_time_and_teams_only(self):
        report = audit(parse_playlist(M3U), index_catalog(CATALOG))
        game = {
            "id": 2026020227, "startTimeUTC": "2026-11-01T18:00:00Z",
            "awayTeam": {"commonName": {"default": "Jets"}},
            "homeTeam": {"commonName": {"default": "Hurricanes"}},
        }
        response = {"gameWeek": [{"date": "2026-11-01", "games": [game]}]}
        matched = annotate_nhl_schedule(report, response, "2026-11-01")
        candidate = matched["nhl_event_candidates"][0]
        self.assertTrue(candidate["official_schedule_match"])
        self.assertEqual(candidate["scheduled_start_utc"], "2026-11-01T18:00:00Z")
        self.assertFalse(candidate["publishable_as_epg"])

    def test_nhl_wrong_date_or_wrong_team_never_matches(self):
        game = {
            "id": 1, "startTimeUTC": "2026-11-01T18:00:00Z",
            "awayTeam": {"commonName": {"default": "Devils"}},
            "homeTeam": {"commonName": {"default": "Hurricanes"}},
        }
        response = {"gameWeek": [{"date": "2026-11-01", "games": [game]}]}
        report = audit(parse_playlist(M3U), index_catalog(CATALOG))
        candidate = annotate_nhl_schedule(report, response, "2026-11-01")["nhl_event_candidates"][0]
        self.assertFalse(candidate["official_schedule_match"])
        self.assertNotIn("scheduled_start_utc", candidate)

    def test_nhl_duplicate_official_candidates_are_ambiguous(self):
        game = {
            "id": 1, "startTimeUTC": "2026-11-01T18:00:00Z",
            "awayTeam": {"commonName": {"default": "Jets"}},
            "homeTeam": {"commonName": {"default": "Hurricanes"}},
        }
        response = {"gameWeek": [{"date": "2026-11-01", "games": [game, {**game, "id": 2}]}]}
        report = audit(parse_playlist(M3U), index_catalog(CATALOG))
        candidate = annotate_nhl_schedule(report, response, "2026-11-01")["nhl_event_candidates"][0]
        self.assertFalse(candidate["official_schedule_match"])


if __name__ == "__main__":
    unittest.main()
