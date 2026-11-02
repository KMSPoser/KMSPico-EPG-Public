#!/usr/bin/env python3
"""Privately audit *future programme coverage* for possible XMLTV ID matches.

This is a read-only compatibility report, not a channel-identity verifier.
It never contacts an IPTV stream, prints a playlist URL, republishes any
programme descriptions, or changes a TiviMate playlist/EPG assignment.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET

from catalog_audit import parse_playlist
from guide_compatibility import channel_ids_from_xmltv, compatibility_report


_XMLTV_TIME = re.compile(r"^(\d{14})\s+([+-]\d{4})$")


def parse_xmltv_time(value: str) -> datetime | None:
    """Accept full XMLTV timestamps with explicit timezone information."""
    if not _XMLTV_TIME.fullmatch(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z").astimezone(timezone.utc)
    except ValueError:
        return None


def candidate_pairs(playlist: list[dict], guide_ids: list[str]) -> tuple[set[str], dict[str, str]]:
    """Return exact guide IDs and uniquely casefold-matched *candidates*."""
    main_ids = {e["channel_id"] for e in playlist
                if e["channel_id"] and not e["channel_id"].casefold().startswith("dummy-")}
    guide_set = set(guide_ids)
    folded: dict[str, set[str]] = defaultdict(set)
    for guide_id in guide_set:
        folded[guide_id.casefold()].add(guide_id)
    exact = main_ids & guide_set
    case_only = {}
    for main_id in main_ids - exact:
        matches = folded.get(main_id.casefold(), set())
        if len(matches) == 1:
            case_only[main_id] = next(iter(matches))
    return exact, case_only


def _covered_hours(intervals: list[tuple[datetime, datetime]]) -> float:
    if not intervals:
        return 0.0
    intervals.sort()
    start, stop = intervals[0]
    total = timedelta()
    for next_start, next_stop in intervals[1:]:
        if next_start <= stop:
            stop = max(stop, next_stop)
        else:
            total += stop - start
            start, stop = next_start, next_stop
    total += stop - start
    return round(total.total_seconds() / 3600, 2)


def coverage_report(playlist: list[dict], guide_path: Path, *,
                    now: datetime, hours: int = 48) -> dict:
    """Stream a complete local XMLTV source and aggregate matched airtime."""
    if hours < 1 or hours > 168:
        raise ValueError("Window must be between 1 and 168 hours")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Window start must be timezone-aware")
    begin = now.astimezone(timezone.utc)
    end = begin + timedelta(hours=hours)

    guide_ids = channel_ids_from_xmltv(guide_path)
    base = compatibility_report(playlist, guide_ids)
    exact, case_only = candidate_pairs(playlist, guide_ids)
    tracked = exact | set(case_only.values())
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    programmes: dict[str, int] = defaultdict(int)
    invalid_times = 0
    opener = gzip.open if guide_path.name.lower().endswith(".gz") else open
    with opener(guide_path, "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty or malformed XMLTV document") from exc
        if root.tag != "tv":
            raise ValueError("Expected an XMLTV <tv> root element")
        for event, elem in context:
            if event != "end":
                continue
            if elem.tag == "programme":
                target = elem.get("channel", "")
                if target in tracked:
                    start = parse_xmltv_time(elem.get("start", ""))
                    stop = parse_xmltv_time(elem.get("stop", ""))
                    if start is None or stop is None or stop <= start:
                        invalid_times += 1
                    elif start < end and stop > begin:
                        intervals[target].append((max(begin, start), min(end, stop)))
                        programmes[target] += 1
                root.clear()
            elif elem.tag == "channel":
                root.clear()

    exact_hours = [_covered_hours(intervals[id_]) for id_ in exact]
    case_hours = [_covered_hours(intervals[id_]) for id_ in case_only.values()]
    base.update({
        "status": "private_schedule_coverage_not_live_stream_verification",
        "window_start_utc": begin.isoformat(),
        "window_hours": hours,
        "exact_ids_with_programmes_in_window": sum(x > 0 for x in exact_hours),
        "case_only_ids_with_programmes_in_window": sum(x > 0 for x in case_hours),
        "case_only_ids_with_at_least_24h_coverage": sum(x >= 24 for x in case_hours),
        "median_case_only_hours_covered": statistics.median(case_hours) if case_hours else 0,
        "programmes_for_exact_ids_in_window": sum(programmes[x] for x in exact),
        "programmes_for_case_only_ids_in_window": sum(programmes[x] for x in case_only.values()),
        "invalid_timestamps_in_matched_programmes": invalid_times,
        "guide_programme_titles_not_recorded": True,
    })
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path,
                        help="Private local M3U; stream URLs are discarded")
    parser.add_argument("--guide", required=True, type=Path,
                        help="Private local XMLTV .xml or .xml.gz")
    parser.add_argument("--hours", default=48, type=int,
                        help="Future schedule window (1-168h, default: 48)")
    args = parser.parse_args()
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    report = coverage_report(playlist, args.guide, now=datetime.now(timezone.utc), hours=args.hours)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
