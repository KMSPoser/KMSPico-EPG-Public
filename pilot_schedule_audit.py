#!/usr/bin/env python3
"""Privately measure whether TVmaze episode listings could support an Eagle pilot.

This diagnostic never verifies IPTV stream identity, changes Main, or writes
XMLTV. It reads local playlist/catalog data only to choose the existing safe
review queue; requests to TVmaze contain calendar dates alone.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from catalog_audit import (annotate_tvmaze_discovery, index_catalog,
                           parse_playlist, pilot_review_queue)
from tvmaze_source import fetch_us_schedule


def _intervals_for_network(schedules: list[list[dict]], *, kind: str,
                           network_id: int, network_name: str,
                           begin: datetime, end: datetime) -> tuple[list[tuple[datetime, datetime]], int]:
    """Return clipped episode intervals, never programme titles or URLs."""
    unique = set()
    for day in schedules:
        for episode in day:
            if not isinstance(episode, dict) or not isinstance(episode.get("show"), dict):
                continue
            show = episode["show"]
            actual_kind = "network" if show.get("network") else "webChannel"
            network = show.get(actual_kind)
            if (actual_kind != kind or not isinstance(network, dict)
                    or network.get("id") != network_id
                    or network.get("name") != network_name):
                continue
            value, runtime = episode.get("airstamp"), episode.get("runtime")
            if (not isinstance(value, str)
                    or not isinstance(show.get("name"), str) or not show["name"].strip()
                    or not isinstance(episode.get("url"), str)
                    or not episode["url"].startswith("https://www.tvmaze.com/episodes/")
                    or type(runtime) is not int or not 1 <= runtime <= 720):
                continue
            try:
                start = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if start.tzinfo is None:
                    continue
                start = start.astimezone(timezone.utc)
                stop = start + timedelta(minutes=runtime)
            except (ValueError, OverflowError):
                continue
            if start < end and stop > begin:
                unique.add((max(begin, start), min(end, stop)))
    return sorted(unique), len(unique)


def _coverage(intervals: list[tuple[datetime, datetime]], *,
              begin: datetime, end: datetime) -> tuple[float, float]:
    """Return union hours and longest uncovered gap within the audit window."""
    merged: list[tuple[datetime, datetime]] = []
    for start, stop in intervals:
        if merged and start <= merged[-1][1]:
            prior_start, prior_stop = merged[-1]
            merged[-1] = (prior_start, max(prior_stop, stop))
        else:
            merged.append((start, stop))
    covered = sum((stop - start).total_seconds() for start, stop in merged) / 3600
    cursor = begin
    gaps = []
    for start, stop in merged:
        gaps.append((start - cursor).total_seconds() / 3600)
        cursor = stop
    gaps.append((end - cursor).total_seconds() / 3600)
    return round(covered, 2), round(max(gaps), 2)


def pilot_schedule_report(playlist: list[dict], catalog: dict[str, dict],
                          schedules: list[list[dict]], *, now: datetime,
                          window_hours: int = 48) -> dict:
    """Produce a private, explicitly unapproved coverage screen for all pilots."""
    if not 1 <= window_hours <= 168:
        raise ValueError("Window must be between 1 and 168 hours")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Window start must be timezone-aware")
    if not schedules or any(not isinstance(day, list) for day in schedules):
        raise ValueError("At least one valid daily schedule is required")
    begin = now.astimezone(timezone.utc)
    end = begin + timedelta(hours=window_hours)
    queue = pilot_review_queue(playlist, catalog)
    annotate_tvmaze_discovery({"pilot_review_queue": queue}, schedules)
    candidates = []
    for candidate in queue:
        hint = candidate.get("proposed_tvmaze_mapping")
        intervals, episode_count = ([], 0)
        if hint:
            intervals, episode_count = _intervals_for_network(
                schedules, kind=hint["kind"],
                network_id=hint["tvmaze_network_id"],
                network_name=hint["tvmaze_network_name"],
                begin=begin, end=end)
        covered, longest_gap = _coverage(intervals, begin=begin, end=end)
        candidates.append({
            "channel_name": candidate["playlist_name"],
            "original_tvg_id": candidate["channel_id"],
            "tvmaze_discovery_status": candidate["tvmaze_discovery_status"],
            "tvmaze_network_name": hint["tvmaze_network_name"] if hint else None,
            "tvmaze_network_id": hint["tvmaze_network_id"] if hint else None,
            "episode_intervals_in_window": episode_count,
            "hours_covered": covered,
            "coverage_percent": round(covered / window_hours * 100, 2),
            "longest_uncovered_gap_hours": longest_gap,
            "actual_stream_verified": False,
            "approved_for_public_guide": False,
        })
    return {
        "version": 1,
        "status": "private_pilot_coverage_not_broadcaster_verification",
        "window_start_utc": begin.isoformat(),
        "window_hours": window_hours,
        "tvmaze_license": "CC BY-SA; attribution and share-alike required",
        "summary": {
            "pilot_candidates": len(candidates),
            "candidates_with_source_identity_hints": sum(
                c["tvmaze_network_id"] is not None for c in candidates),
            "candidates_with_episode_intervals": sum(
                c["episode_intervals_in_window"] > 0 for c in candidates),
            "channels_approved_for_public_guide": 0,
            "ready_to_replace_epg41": False,
        },
        "candidates": candidates,
        "privacy": {
            "no_stream_urls": True,
            "no_stream_ids": True,
            "no_programme_titles": True,
            "no_credentials": True,
            "do_not_publish_report": True,
        },
        "warning": "TVmaze tracks episodes, not a complete 24-hour linear guide."
                   " No network identity or broadcast has been verified in TiviMate.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--window-hours", type=int, default=48)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    # Include the prior day to capture programmes crossing UTC midnight.
    # A 48-hour window needs dates -1, 0, 1, 2; no playlist data is sent.
    days = [((now.date() + timedelta(days=offset)).isoformat())
            for offset in range(-1, ((args.window_hours - 1) // 24) + 2)]
    schedules = [fetch_us_schedule(day) for day in days]
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    catalog = index_catalog(args.catalog.read_text(encoding="utf-8"))
    print(json.dumps(pilot_schedule_report(playlist, catalog, schedules,
                                           now=now, window_hours=args.window_hours), indent=2))


if __name__ == "__main__":
    main()
