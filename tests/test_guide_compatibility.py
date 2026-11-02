import gzip
from pathlib import Path
import tempfile
import unittest

from catalog_audit import parse_playlist
from guide_compatibility import channel_ids_from_xmltv, compatibility_report


PLAYLIST = '''#EXTM3U
#EXTINF:-1 tvg-id="espn.us",ESPN
https://example.invalid/secret-account/secret-password/101.m3u8
#EXTINF:-1 tvg-id="cnn.us",CNN
https://example.invalid/secret-account/secret-password/102.m3u8
#EXTINF:-1 tvg-id="espn.us",ESPN Backup
https://example.invalid/secret-account/secret-password/103.m3u8
#EXTINF:-1 tvg-id="dummy-1",Unassigned Event
https://example.invalid/secret-account/secret-password/104.m3u8
'''


class GuideCompatibilityTests(unittest.TestCase):
    def test_exact_vs_case_only_are_counted_without_approving_any_mapping(self):
        report = compatibility_report(parse_playlist(PLAYLIST), ["ESPN.us", "cnn.us"])
        self.assertEqual(report["main_playlist_channels"], 4)
        self.assertEqual(report["distinct_nonplaceholder_main_ids"], 2)
        self.assertEqual(report["exact_id_matches"], 1)
        self.assertEqual(report["case_only_candidates_not_automatically_assigned"], 1)
        self.assertEqual(report["case_only_candidate_playlist_channels"], 2)
        self.assertEqual(report["exact_match_playlist_channels"], 1)
        self.assertEqual(report["unmatched_main_ids"], 0)
        self.assertFalse(report["ready_to_replace_existing_epg"])
        self.assertTrue(report["playlist_and_guide_unchanged"])
        self.assertNotIn("secret-password", str(report))
        self.assertNotIn("example.invalid", str(report))

    def test_reused_main_id_is_counted_but_not_rewritten(self):
        playlist = parse_playlist(PLAYLIST)
        before = [dict(channel) for channel in playlist]
        report = compatibility_report(playlist, ["espn.us"])
        self.assertEqual(report["exact_id_matches"], 1)
        self.assertEqual(report["exact_match_playlist_channels"], 2)
        self.assertEqual(report["unmatched_main_ids"], 1)
        self.assertEqual(playlist, before)

    def test_guide_casefold_collision_is_reported_as_ambiguous(self):
        report = compatibility_report(parse_playlist(PLAYLIST),
                                      ["ESPN.us", "Espn.us", "CNN.us"])
        self.assertEqual(report["case_only_candidates_not_automatically_assigned"], 1)
        self.assertEqual(report["ambiguous_casefold_candidates"], 1)
        self.assertEqual(report["guide_repeated_exact_ids"], 0)

    def test_guide_repeated_id_is_counted(self):
        report = compatibility_report(parse_playlist(PLAYLIST), ["espn.us", "espn.us"])
        self.assertEqual(report["guide_repeated_exact_ids"], 1)

    def test_streaming_parser_supports_xml_and_gzip(self):
        source = (b'<?xml version="1.0"?><tv><channel id="ESPN.us"/>'
                  b'<channel id="cnn.us"/><programme channel="ESPN.us" '
                  b'start="20261102000000 +0000" stop="20261102010000 +0000"/></tv>')
        with tempfile.TemporaryDirectory() as path:
            folder = Path(path)
            plain = folder / "guide.xml"
            packed = folder / "guide.xml.gz"
            plain.write_bytes(source)
            packed.write_bytes(gzip.compress(source))
            self.assertEqual(channel_ids_from_xmltv(plain), ["ESPN.us", "cnn.us"])
            self.assertEqual(channel_ids_from_xmltv(packed), ["ESPN.us", "cnn.us"])

    def test_rejects_non_xmltv_document(self):
        with tempfile.TemporaryDirectory() as path:
            wrong = Path(path) / "wrong.xml"
            wrong.write_text("<html></html>", encoding="utf-8")
            with self.assertRaises(ValueError):
                channel_ids_from_xmltv(wrong)

    def test_empty_guide_has_clear_error(self):
        with tempfile.TemporaryDirectory() as path:
            wrong = Path(path) / "empty.xml"
            wrong.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "Empty or malformed XMLTV"):
                channel_ids_from_xmltv(wrong)


if __name__ == "__main__":
    unittest.main()
