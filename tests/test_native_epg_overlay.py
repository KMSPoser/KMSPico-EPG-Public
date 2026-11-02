"""Synthetic-only tests for the private, unapproved Eagle XMLTV candidate."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from native_epg_overlay import (
    build_candidate, proposed_links, write_private_candidate,
)


NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
ONE_DAY = 'start="20261102000000 +0000" stop="20261103000000 +0000"'


class NativeEPGOverlayTest(unittest.TestCase):
    def _fixtures(self, directory: Path, *, baseline_id="old.guide",
                  programmes=None, duplicate_channel=False):
        baseline = directory / "baseline.xml"
        native = directory / "native.xml"
        baseline.write_text(f'<tv><channel id="{baseline_id}"/></tv>', encoding="utf-8")
        if programmes is None:
            programmes = [f'<programme channel="native.id" {ONE_DAY}>'
                          '<title>Scheduled show</title><desc>Explanation</desc></programme>']
        duplicate = '<channel id="native.id"/>' if duplicate_channel else ""
        native.write_text(
            '<tv><channel id="native.id"/>' + duplicate
            + "".join(programmes) + '</tv>',
            encoding="utf-8"
        )
        return baseline, native

    def _data(self):
        playlist = [{"channel_id": "eagle.original", "name": "News Example",
                     "stream_id": "100"}]
        catalog = {"100": {"epg_id": "native.id"}}
        return playlist, catalog

    def test_preserves_eagle_id_and_never_approves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory))
            playlist, catalog = self._data()
            tree, report = build_candidate(
                playlist, catalog, baseline=base, eagle=native, now=NOW
            )
            root = tree.getroot()
            self.assertEqual(report["candidate_channels"], 1)
            self.assertEqual(report["candidate_programmes"], 1)
            self.assertFalse(report["approved_for_public_guide"])
            self.assertEqual(root.find("channel").get("id"), "eagle.original")
            self.assertEqual(root.find("programme").get("channel"), "eagle.original")
            self.assertEqual(root.find("programme/title").text, "Scheduled show")
            self.assertIsNone(root.find("programme/icon"))

    def test_baseline_channels_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), baseline_id="eagle.original")
            tree, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(len(tree.getroot()), 0)
            self.assertEqual(report["mapping_counts"]["already_declared_by_baseline"], 1)

    def test_conflicting_same_original_id_is_excluded(self):
        playlist, catalog = self._data()
        playlist.append({"channel_id": "eagle.original", "name": "Another",
                         "stream_id": "101"})
        catalog["101"] = {"epg_id": "another.id"}
        links, stats = proposed_links(playlist, catalog, set())
        self.assertEqual(links, {})
        self.assertEqual(stats["conflicting_provider_mapping"], 1)

    def test_unmapped_duplicate_main_id_is_not_auto_promoted(self):
        playlist, catalog = self._data()
        playlist.append({"channel_id": "eagle.original", "name": "Backup",
                         "stream_id": "101"})
        catalog["101"] = {"epg_id": ""}
        links, stats = proposed_links(playlist, catalog, set())
        self.assertEqual(links, {})
        self.assertEqual(stats["missing_provider_mapping"], 1)

    def test_consistent_shared_id_is_flagged_for_manual_review(self):
        playlist, catalog = self._data()
        playlist.append({"channel_id": "eagle.original", "name": "Backup",
                         "stream_id": "101"})
        catalog["101"] = {"epg_id": "native.id"}
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory))
            _, report = build_candidate(playlist, catalog, baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_shared_main_ids_needing_review"], 1)

    def test_duplicate_source_channel_and_programme_are_deduplicated(self):
        programme = (f'<programme channel="native.id" {ONE_DAY}>'
                     '<title>Scheduled show</title></programme>')
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=[programme, programme],
                                          duplicate_channel=True)
            tree, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_programmes"], 1)
            self.assertEqual(len(tree.getroot().findall("programme")), 1)
            self.assertEqual(report["source_checks"]["source_duplicate_channel_ids"], 1)
            self.assertEqual(report["source_checks"]["duplicate_programmes_removed"], 1)

    def test_contradictory_programme_titles_exclude_source(self):
        programmes = [
            f'<programme channel="native.id" {ONE_DAY}><title>News</title></programme>',
            f'<programme channel="native.id" {ONE_DAY}><title>Sports</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            tree, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(report["selection_counts"]["source_schedule_conflict"], 1)
            self.assertEqual(len(tree.getroot()), 0)

    def test_partially_overlapping_different_titles_are_excluded(self):
        programmes = [
            '<programme channel="native.id" start="20261102000000 +0000" '
            'stop="20261102160000 +0000"><title>News</title></programme>',
            '<programme channel="native.id" start="20261102150000 +0000" '
            'stop="20261103000000 +0000"><title>Sports</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            tree, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(report["selection_counts"]["source_schedule_overlap"], 1)
            self.assertEqual(report["source_checks"]["partial_overlap_intervals"], 1)
            self.assertEqual(report["source_checks"]["source_ids_with_partial_overlaps"], 1)
            self.assertFalse(report["approved_for_public_guide"])
            self.assertEqual(len(tree.getroot()), 0)

    def test_same_title_time_shift_is_also_withheld(self):
        programmes = [
            '<programme channel="native.id" start="20261102000000 +0000" '
            'stop="20261102160000 +0000"><title>News</title></programme>',
            '<programme channel="native.id" start="20261102150000 +0000" '
            'stop="20261103000000 +0000"><title>News</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            _, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(report["selection_counts"]["source_schedule_overlap"], 1)

    def test_adjacent_nonoverlapping_programmes_stay_candidates(self):
        programmes = [
            '<programme channel="native.id" start="20261102000000 +0000" '
            'stop="20261102120000 +0000"><title>Morning</title></programme>',
            '<programme channel="native.id" start="20261102120000 +0000" '
            'stop="20261103000000 +0000"><title>Evening</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            tree, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 1)
            self.assertEqual(report["candidate_programmes"], 2)
            self.assertEqual(report["source_checks"]["source_ids_with_partial_overlaps"], 0)
            self.assertEqual(len(tree.getroot().findall("programme")), 2)

    def test_nested_intervals_detected_without_quadratic_comparison(self):
        programmes = [
            f'<programme channel="native.id" {ONE_DAY}><title>Full day</title></programme>',
            '<programme channel="native.id" start="20261102010000 +0000" '
            'stop="20261102020000 +0000"><title>Short A</title></programme>',
            '<programme channel="native.id" start="20261102030000 +0000" '
            'stop="20261102040000 +0000"><title>Short B</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            _, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(report["source_checks"]["partial_overlap_intervals"], 2)

    def test_invalid_or_short_source_schedule_not_exported(self):
        programmes = [
            '<programme channel="native.id" start="bad" stop="bad">'
            '<title>Incorrect</title></programme>',
            '<programme channel="native.id" start="20261102000000 +0000" '
            'stop="20261102020000 +0000"><title>Short</title></programme>',
        ]
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory), programmes=programmes)
            _, report = build_candidate(*self._data(), baseline=base, eagle=native, now=NOW)
            self.assertEqual(report["candidate_channels"], 0)
            self.assertEqual(report["source_checks"]["invalid_source_timestamps"], 1)
            self.assertEqual(report["selection_counts"]["under_95pct_coverage"], 1)

    def test_output_is_private_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "private_candidate.xml"
            tree = ET.ElementTree(ET.Element("tv"))
            write_private_candidate(tree, out)
            self.assertEqual(os.stat(out).st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private_candidate(tree, out)
            with self.assertRaises(ValueError):
                write_private_candidate(tree, Path(__file__).resolve().parents[1] / "docs" / "guide.xml")

    def test_rejects_oversized_window(self):
        with tempfile.TemporaryDirectory() as directory:
            base, native = self._fixtures(Path(directory))
            with self.assertRaises(ValueError):
                build_candidate(*self._data(), baseline=base, eagle=native, now=NOW, hours=49)


if __name__ == "__main__":
    unittest.main()
