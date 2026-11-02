#!/usr/bin/env python3
"""Build an unapproved PRIVATE XMLTV supplement from an account-owned guide.

This is an offline candidate for manual stream verification, not permission to
redistribute source schedules or a ready-to-install TiviMate EPG. It never
changes the playlist, its original tvg-ids, Favorites, or the public guide.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from catalog_audit import index_catalog, parse_playlist
from guide_coverage import parse_xmltv_time
from source_comparison import interval_metrics, scan_xmltv


ALLOWED_PROGRAMME_TAGS = frozenset({
    "title", "sub-title", "desc", "category", "date", "episode-num",
    "rating", "star-rating", "previously-shown", "new", "premiere",
})


def proposed_links(playlist: list[dict], catalog: dict[str, dict],
                   baseline_ids: set[str]) -> tuple[dict[str, dict], Counter]:
    """Propose only consistent stream-id-based links for ids absent in baseline."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in playlist:
        original = entry.get("channel_id", "")
        if original and not original.casefold().startswith("dummy-"):
            groups[original].append(entry)
    links: dict[str, dict] = {}
    stats: Counter[str] = Counter()
    for original, entries in groups.items():
        if original in baseline_ids:
            stats["already_declared_by_baseline"] += 1
            continue
        provider_ids = [catalog.get(e.get("stream_id"), {}).get("epg_id", "")
                        for e in entries]
        if not all(provider_ids):
            stats["missing_provider_mapping"] += 1
            continue
        if len(set(provider_ids)) != 1:
            stats["conflicting_provider_mapping"] += 1
            continue
        links[original] = {
            "source_id": provider_ids[0],
            "display_names": sorted({e.get("name", "") for e in entries if e.get("name")}),
            "shared_main_id": len(entries) > 1,
        }
    stats["candidate_links"] = len(links)
    return links, stats


def _copy_programme(source: ET.Element) -> ET.Element:
    """Retain schedule text, omit logos/links/custom attrs, assign ID later."""
    result = ET.Element("programme", {
        "start": source.get("start", ""), "stop": source.get("stop", "")
    })
    for child in source:
        if child.tag in ALLOWED_PROGRAMME_TAGS:
            result.append(deepcopy(child))
    return result


def scan_schedules(path: Path, wanted_ids: set[str], *,
                   begin: datetime, end: datetime) -> tuple[dict, Counter]:
    """Parse only requested programme slots; reject contradictory exact slots."""
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    slots: dict[str, dict[tuple[datetime, datetime], tuple[str, ET.Element]]] = defaultdict(dict)
    declarations: Counter[str] = Counter()
    contradictory: set[str] = set()
    stats: Counter[str] = Counter()
    with opener(path, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty or malformed XMLTV source") from exc
        if root.tag != "tv":
            raise ValueError("Expected XMLTV <tv> root")
        for event, elem in context:
            if event != "end":
                continue
            if elem.tag == "channel":
                channel_id = elem.get("id", "").strip()
                if channel_id:
                    declarations[channel_id] += 1
                root.clear()
            elif elem.tag == "programme":
                channel_id = elem.get("channel", "").strip()
                if channel_id in wanted_ids:
                    start = parse_xmltv_time(elem.get("start", ""))
                    stop = parse_xmltv_time(elem.get("stop", ""))
                    if start is None or stop is None or stop <= start:
                        stats["invalid_source_timestamps"] += 1
                    elif start < end and stop > begin:
                        title = (elem.findtext("title") or "").strip()
                        if not title:
                            stats["untitled_programmes"] += 1
                        else:
                            key = (start, stop)
                            prior = slots[channel_id].get(key)
                            if prior:
                                if prior[0] != title:
                                    contradictory.add(channel_id)
                                    stats["contradictory_exact_slots"] += 1
                                else:
                                    stats["duplicate_programmes_removed"] += 1
                            else:
                                slots[channel_id][key] = (title, _copy_programme(elem))
                root.clear()
    stats["source_duplicate_channel_ids"] = sum(n > 1 for n in declarations.values())
    return {
        "declared": set(declarations),
        "slots": slots,
        "contradictory": contradictory,
    }, stats


def build_candidate(playlist: list[dict], catalog: dict[str, dict], *,
                    baseline: Path, eagle: Path, now: datetime,
                    hours: int = 24) -> tuple[ET.ElementTree, dict]:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    if not 1 <= hours <= 48:
        raise ValueError("Window must be 1 to 48 hours")
    begin = now.astimezone(timezone.utc)
    end = begin + timedelta(hours=hours)
    # Baseline declarations only; never import or copy baseline programmes.
    base = scan_xmltv(baseline, set(), begin=begin, end=end)
    links, mapping_stats = proposed_links(playlist, catalog, set(base["declared"]))
    native, source_stats = scan_schedules(
        eagle, {v["source_id"] for v in links.values()}, begin=begin, end=end
    )
    document = ET.Element("tv", {
        "generator-info-name": "Private Eagle overlay CANDIDATE - not approved"
    })
    accepted: dict[str, str] = {}
    result_stats: Counter[str] = Counter()
    for target, info in sorted(links.items()):
        source_id = info["source_id"]
        if source_id not in native["declared"]:
            result_stats["source_id_missing"] += 1
            continue
        if source_id in native["contradictory"]:
            result_stats["source_schedule_conflict"] += 1
            continue
        programmes = native["slots"].get(source_id, {})
        intervals = [(max(begin, start), min(end, stop))
                     for start, stop in programmes if start < end and stop > begin]
        coverage, _ = interval_metrics(intervals, begin=begin, end=end)
        if coverage < 0.95:
            result_stats["under_95pct_coverage"] += 1
            continue
        accepted[target] = source_id
        if info["shared_main_id"]:
            result_stats["accepted_shared_main_ids_requiring_verification"] += 1
        channel = ET.SubElement(document, "channel", {"id": target})
        for name in info["display_names"]:
            ET.SubElement(channel, "display-name").text = name

    for target, source_id in sorted(accepted.items()):
        for (_, _), (_, programme) in sorted(native["slots"][source_id].items()):
            cloned = deepcopy(programme)
            cloned.set("channel", target)
            document.append(cloned)
            result_stats["programme_entries"] += 1
    result = {
        "status": "private_unapproved_overlay_candidate",
        "window_hours": hours,
        "baseline_ids_left_untouched": True,
        "playlist_and_favorites_unchanged": True,
        "candidate_channels": len(accepted),
        "candidate_programmes": result_stats["programme_entries"],
        "candidate_shared_main_ids_needing_review": result_stats[
            "accepted_shared_main_ids_requiring_verification"],
        "mapping_counts": dict(mapping_stats),
        "source_checks": dict(source_stats),
        "selection_counts": {
            key: result_stats[key] for key in (
                "source_id_missing", "source_schedule_conflict",
                "under_95pct_coverage")
        },
        "stream_identity_verified": False,
        "redistribution_rights_verified": False,
        "approved_for_public_guide": False,
        "ready_to_replace_epg41": False,
    }
    return ET.ElementTree(document), result


def write_private_candidate(tree: ET.ElementTree, path: Path) -> None:
    """Write once with mode 0600; refuse any path within this public repo."""
    project_root = Path(__file__).resolve().parent
    absolute = path.resolve()
    if absolute.is_relative_to(project_root) or path.suffix.lower() != ".xml":
        raise ValueError("Private XML output must be outside the public repo")
    fd = os.open(absolute, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            tree.write(output, encoding="utf-8", xml_declaration=True)
    except Exception:
        absolute.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--private-output", type=Path)
    args = parser.parse_args()
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    catalog = index_catalog(args.catalog.read_text(encoding="utf-8"))
    tree, report = build_candidate(
        playlist, catalog, baseline=args.baseline, eagle=args.native,
        now=datetime.now(timezone.utc), hours=args.hours
    )
    if args.private_output is not None:
        write_private_candidate(tree, args.private_output)
        report["private_candidate_written"] = True
    else:
        report["private_candidate_written"] = False
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
