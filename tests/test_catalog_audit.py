import json
import unittest

from catalog_audit import (
    annotate_nhl_schedule, annotate_tvmaze_discovery, audit, index_catalog, mapping_preflight,
    numeric_stream_id, parse_playlist, pilot_review_queue, shared_epg_ids,
)


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


def approved_tvmaze(channel_id="cw8kpax.us", name="Missoula | CW"):
    return {"version": 1, "channels": [{
        "channel_id": channel_id, "channel_name": name,
        "tvmaze_network_id": 190, "tvmaze_network_name": "CW",
        "kind": "network", "operator_verified": True,
    }]}


class CatalogAuditTests(unittest.TestCase):
    def test_preflight_with_no_approved_mapping_is_not_epg_readiness(self):
        report = mapping_preflight(parse_playlist(M3U), index_catalog(CATALOG),
                                   {"version": 1, "channels": []})
        self.assertEqual(report["checked_mappings"], 0)
        self.assertTrue(report["structurally_consistent"])
        self.assertTrue(report["not_a_publication_approval"])
        self.assertIn("not_live_stream_verification", report["status"])

    def test_preflight_matches_unique_existing_main_id_without_modification(self):
        entries = parse_playlist(M3U)
        original = [dict(e) for e in entries]
        report = mapping_preflight(entries, index_catalog(CATALOG), approved_tvmaze())
        self.assertEqual(report["checked_mappings"], 1)
        self.assertTrue(report["structurally_consistent"])
        self.assertEqual(report["blocking_issues"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(entries, original)

    def test_preflight_blocks_shared_existing_main_id_without_rewriting(self):
        entries = parse_playlist(M3U)
        entries.append({**entries[0], "name": "Backup", "channel_id": "CW8KPAX.US"})
        report = mapping_preflight(entries, index_catalog(CATALOG), approved_tvmaze())
        self.assertFalse(report["structurally_consistent"])
        self.assertEqual(report["blocking_issues"][0]["code"], "shared_main_epg_id")
        self.assertEqual(entries[-1]["channel_id"], "CW8KPAX.US")

    def test_preflight_rejects_missing_placeholder_and_case_changed_ids(self):
        entries = parse_playlist(M3U)
        records = index_catalog(CATALOG)
        cases = [
            ("nowhere.us", "not_in_main"),
            ("dummy-4956", "placeholder_epg_id"),
            ("CW8KPAX.US", "exact_id_case_mismatch"),
        ]
        for channel_id, error in cases:
            with self.subTest(channel_id=channel_id):
                result = mapping_preflight(entries, records, approved_tvmaze(channel_id))
                self.assertIn(error, [x["code"] for x in result["blocking_issues"]])

    def test_preflight_warns_on_label_and_provider_disagreement(self):
        entries = parse_playlist(M3U)
        records = index_catalog(json.dumps([
            {"stream_id": 278751, "name": "CW", "epg_channel_id": "other.id"}
        ]))
        report = mapping_preflight(entries, records,
                                   approved_tvmaze(name="Custom CW label"))
        self.assertTrue(report["structurally_consistent"])
        self.assertEqual([x["code"] for x in report["warnings"]],
                         ["custom_display_name", "provider_epg_id_differs"])

    def test_preflight_rejects_unverified_mapping_and_never_exposes_stream_url(self):
        config = approved_tvmaze()
        config["channels"][0]["operator_verified"] = False
        with self.assertRaises(ValueError):
            mapping_preflight(parse_playlist(M3U), index_catalog(CATALOG), config)
        report = mapping_preflight(parse_playlist(M3U), index_catalog(CATALOG),
                                   approved_tvmaze())
        self.assertNotIn("secret-password", json.dumps(report))
        self.assertNotIn("provider.example", json.dumps(report))

    def test_tvmaze_discovery_is_unapproved_even_after_exact_network_match(self):
        report = {"pilot_review_queue": [{"playlist_name": "HGTV", "channel_id": "hgtv.us",
                                           "publishable_as_epg": False}]}
        sample = [{"show": {"network": {"id": 192, "name": "HGTV"}},
                   "airstamp": "2026-11-02T18:00:00Z", "runtime": 30,
                   "url": "https://www.tvmaze.com/episodes/123/test"}]
        candidate = annotate_tvmaze_discovery(report, [sample])["pilot_review_queue"][0]
        self.assertEqual(candidate["tvmaze_episode_count_in_sample"], 1)
        self.assertEqual(candidate["proposed_tvmaze_mapping"]["tvmaze_network_id"], 192)
        self.assertFalse(candidate["proposed_tvmaze_mapping"]["operator_verified"])
        self.assertFalse(candidate["publishable_as_epg"])
        annotate_tvmaze_discovery(report, [[]])
        self.assertNotIn("proposed_tvmaze_mapping", candidate)

    def test_tvmaze_discovery_rejects_ambiguous_network_identity(self):
        report = {"pilot_review_queue": [{"playlist_name": "HGTV", "channel_id": "hgtv.us",
                                           "publishable_as_epg": False}]}
        episodes = [
            {"show": {"network": {"id": i, "name": "HGTV"}}, "runtime": 30,
             "airstamp": "2026-11-02T18:00:00Z",
             "url": "https://www.tvmaze.com/episodes/123/test"}
            for i in (192, 999)
        ]
        candidate = annotate_tvmaze_discovery(report, [episodes])["pilot_review_queue"][0]
        self.assertEqual(candidate["tvmaze_discovery_status"], "ambiguous_network_identity")
        self.assertNotIn("proposed_tvmaze_mapping", candidate)

    def test_tvmaze_discovery_skips_missing_and_unusable_episodes(self):
        report = {"pilot_review_queue": [{"playlist_name": "HGTV", "channel_id": "hgtv.us",
                                           "publishable_as_epg": False}]}
        sample = [{"show": {"network": {"id": 192, "name": "HGTV"}}, "runtime": 0,
                   "url": "https://www.tvmaze.com/episodes/123/test"}]
        sample.append({"show": {"network": {"id": 192, "name": "HGTV"}}, "runtime": 30,
                       "airstamp": "not-a-timestamp",
                       "url": "https://www.tvmaze.com/episodes/124/test"})
        candidate = annotate_tvmaze_discovery(report, [sample])["pilot_review_queue"][0]
        self.assertEqual(candidate["tvmaze_discovery_status"], "not_found_in_sample")
        self.assertNotIn("proposed_tvmaze_mapping", candidate)

    def test_shared_guide_ids_count_redundancy_without_changing_channels(self):
        entries = parse_playlist(M3U)
        entries.append({**entries[0], "name": "Missoula | CW Backup", "channel_id": "CW8KPAX.US"})
        entries.append({**entries[1], "name": "NHL Event 02"})
        self.assertEqual(shared_epg_ids(entries), {"cw8kpax.us": 2})
        report = audit(entries, index_catalog(CATALOG))
        self.assertEqual(report["counts"]["shared_epg_id_values"], 1)
        self.assertEqual(report["counts"]["channels_using_shared_epg_ids"], 2)
        self.assertEqual(entries[0]["channel_id"], "cw8kpax.us")

    def test_pilot_queue_requires_unique_us_id_and_provider_agreement(self):
        playlist = parse_playlist('''#EXTM3U
#EXTINF:-1 tvg-id="hgtv.us" group-title="Entertainment",HGTV
https://provider.example/user/hidden/150.m3u8
#EXTINF:-1 tvg-id="amc.ca" group-title="Canada",AMC
https://provider.example/user/hidden/151.m3u8
#EXTINF:-1 tvg-id="fx.us" group-title="Entertainment",FX
https://provider.example/user/hidden/152.m3u8
''')
        records = index_catalog(json.dumps([
            {"stream_id": 150, "name": "HGTV HD", "epg_channel_id": "hgtv.us"},
            {"stream_id": 151, "name": "AMC Canada", "epg_channel_id": "amc.ca"},
            {"stream_id": 152, "name": "FX HD", "epg_channel_id": "wrong.id"},
        ]))
        queue = pilot_review_queue(playlist, records)
        self.assertEqual([q["playlist_name"] for q in queue], ["HGTV"])
        self.assertFalse(queue[0]["publishable_as_epg"])
        self.assertTrue(queue[0]["requires_live_verification"])
        self.assertNotIn("provider.example", json.dumps(queue))

    def test_pilot_queue_excludes_duplicate_ids_and_ambiguous_labels(self):
        playlist = parse_playlist('''#EXTM3U
#EXTINF:-1 tvg-id="hgtv.us",HGTV
https://provider.example/user/hidden/150.m3u8
#EXTINF:-1 tvg-id="hgtv.us",HGTV Backup
https://provider.example/user/hidden/151.m3u8
#EXTINF:-1 tvg-id="cnn.us",CNN
https://provider.example/user/hidden/152.m3u8
#EXTINF:-1 tvg-id="cnn2.us",CNN
https://provider.example/user/hidden/153.m3u8
''')
        records = index_catalog(json.dumps([
            {"stream_id": i, "name": "test", "epg_channel_id": guide}
            for i, guide in [(150, "hgtv.us"), (151, "hgtv.us"), (152, "cnn.us"), (153, "cnn2.us")]
        ]))
        self.assertEqual(pilot_review_queue(playlist, records), [])

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
