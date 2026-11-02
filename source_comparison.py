#!/usr/bin/env python3
"""Compare candidate XMLTV sources against Eagle's existing IDs, privately.

This is an offline *schedule-availability* audit, never a broadcaster identity,
copyright permission, playlist compatibility, or publication approval.  It
does not read programme titles, programme descriptions, stream URLs, or
credentials into its report.  All input files remain local and unchanged.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from catalog_audit import parse_playlist
from guide_coverage import parse_xmltv_time


_SOURCE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def parse_candidate(argument: str) -> tuple[str, Path]:
    """A short, public-safe label plus a private local XMLTV path."""
    label, sep, filename = argument.partition("=")
    if not sep or not _SOURCE_LABEL.fullmatch(label) or not filename.strip():
        raise ValueError("Candidate must be LABEL=/private/path/guide.xml[.gz]")
    return label, Path(filename)


def interval_metrics(intervals: list[tuple[datetime, datetime]], *,
                     begin: datetime, end: datetime) -> tuple[float, float]:
    """Return fraction of the window covered and longest uncovered gap (h)."""
    cursor = begin
    longest_gap = 0.0
    covered = 0.0
    for start, stop in sorted(intervals):
        if stop <= cursor:
            continue
        longest_gap = max(longest_gap, (start - cursor).total_seconds())
        effective_start = max(cursor, start)
        covered += (stop - effective_start).total_seconds()
        cursor = stop
    longest_gap = max(longest_gap, (end - cursor).total_seconds())
    duration = (end - begin).total_seconds()
    return covered / duration, longest_gap / 3600


def scan_xmltv(source_path: Path, wanted_folded: set[str], *,
               begin: datetime, end: datetime) -> dict:
    """One streaming pass through a local XMLTV; discard all programme text."""
    declared: Counter[str] = Counter()
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    programme_counts: Counter[str] = Counter()
    invalid_timestamps = 0
    opener = gzip.open if source_path.name.lower().endswith(".gz") else open
    with opener(source_path, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty or malformed XMLTV document") from exc
        if root.tag != "tv":
            raise ValueError("Expected an XMLTV <tv> root element")
        for event, elem in context:
            if event != "end":
                continue
            if elem.tag == "channel":
                channel_id = elem.get("id", "").strip()
                if channel_id:
                    declared[channel_id] += 1
                root.clear()
            elif elem.tag == "programme":
                channel_id = elem.get("channel", "").strip()
                if channel_id.casefold() in wanted_folded:
                    start = parse_xmltv_time(elem.get("start", ""))
                    stop = parse_xmltv_time(elem.get("stop", ""))
                    if start is None or stop is None or stop <= start:
                        invalid_timestamps += 1
                    elif start < end and stop > begin:
                        intervals[channel_id].append((max(begin, start), min(end, stop)))
                        programme_counts[channel_id] += 1
                root.clear()
    return {
        "declared": declared,
        "intervals": intervals,
        "programme_counts": programme_counts,
        "invalid_timestamps": invalid_timestamps,
    }


def compare_sources(playlist: list[dict], candidates: list[tuple[str, Path]], *,
                    now: datetime, hours: int = 48) -> dict:
    if not 1 <= hours <= 168:
        raise ValueError("Window must be between 1 and 168 hours")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Window start must be timezone-aware")
    if not candidates or len(candidates) > 12:
        raise ValueError("Provide between 1 and 12 candidate XMLTV sources")
    labels = [name for name, _ in candidates]
    if any(not _SOURCE_LABEL.fullmatch(name) for name in labels) or len(labels) != len(set(labels)):
        raise ValueError("Source labels must be unique, short and safe")

    begin = now.astimezone(timezone.utc)
    end = begin + timedelta(hours=hours)
    original: Counter[str] = Counter(e["channel_id"] for e in playlist
                                     if e["channel_id"] and not e["channel_id"].casefold().startswith("dummy-"))
    folded_counts = Counter()
    for channel_id, count in original.items():
        folded_counts[channel_id.casefold()] += count

    channels = {key: {"tvg_id": key, "playlist_entries": count,
                      "shared_id": folded_counts[key.casefold()] > 1,
                      "candidate_sources": []}
                for key, count in sorted(original.items())}
    source_summaries = []

    for label, source_path in candidates:
        scan = scan_xmltv(source_path, set(folded_counts), begin=begin, end=end)
        declared = scan["declared"]
        folded: dict[str, set[str]] = defaultdict(set)
        for channel_id in declared:
            folded[channel_id.casefold()].add(channel_id)
        exact_matches = case_only = ambiguous = strong_exact = 0

        for key, row in channels.items():
            if key in declared:
                match = "exact"
                actual_id = key
                exact_matches += 1
            else:
                possible = folded.get(key.casefold(), set())
                if len(possible) == 1:
                    match = "case_only_manual_mapping_required"
                    actual_id = next(iter(possible))
                    case_only += 1
                elif len(possible) > 1:
                    match = "ambiguous_casefold"
                    actual_id = None
                    ambiguous += 1
                else:
                    continue

            intervals = scan["intervals"].get(actual_id, []) if actual_id else []
            fraction, longest = interval_metrics(intervals, begin=begin, end=end)
            if match == "exact" and fraction >= 0.95 and not row["shared_id"]:
                strong_exact += 1
            row["candidate_sources"].append({
                "source": label,
                "id_match": match,
                "future_programme_count": scan["programme_counts"].get(actual_id, 0),
                "window_coverage_percent": round(100 * fraction, 2),
                "longest_uncovered_hours": round(longest, 2),
                "stream_identity_verified": False,
                "redistribution_rights_verified": False,
                "approved_for_public_guide": False,
            })

        source_summaries.append({
            "source": label,
            "declared_unique_ids": len(declared),
            "duplicate_channel_declarations": sum(n > 1 for n in declared.values()),
            "exact_main_id_matches": exact_matches,
            "case_only_manual_mapping_candidates": case_only,
            "ambiguous_casefold_matches": ambiguous,
            "unique_main_ids_with_exact_95pct_schedule_coverage": strong_exact,
            "invalid_timestamps_for_candidate_main_ids": scan["invalid_timestamps"],
            "redistribution_rights_unreviewed": True,
        })

    exact_any = sum(any(c["id_match"] == "exact" for c in row["candidate_sources"])
                    for row in channels.values())
    return {
        "schema_version": 1,
        "status": "private_source_comparison_not_identity_or_rights_verification",
        "window_start_utc": begin.isoformat(),
        "window_hours": hours,
        "main_playlist_entries": len(playlist),
        "distinct_nonplaceholder_main_ids": len(original),
        "unique_exact_ids_found_in_any_source": exact_any,
        "source_summaries": source_summaries,
        "channels": list(channels.values()),
        "privacy": {
            "no_stream_urls_or_credentials": True,
            "no_programme_titles_or_descriptions": True,
            "no_programmes_redistributed": True,
            "private_report_do_not_publish": True,
        },
        "stream_identities_approved": 0,
        "sources_authorized_for_redistribution": 0,
        "ready_to_replace_existing_epg": False,
        "main_playlist_and_candidate_guides_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path, help="Private local M3U")
    parser.add_argument("--candidate", required=True, action="append", metavar="LABEL=PATH",
                        help="Local XMLTV candidate; repeat for each source (max 12)")
    parser.add_argument("--hours", type=int, default=48, help="Future window (1-168h)")
    args = parser.parse_args()
    try:
        candidates = [parse_candidate(raw) for raw in args.candidate]
        playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
        result = compare_sources(playlist, candidates, now=datetime.now(timezone.utc), hours=args.hours)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
