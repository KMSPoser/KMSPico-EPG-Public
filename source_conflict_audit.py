#!/usr/bin/env python3
"""Aggregate-only audit of duplicate/XMLTV contradictory programme titles.

Never emits programme titles, IDs, descriptions, stream URLs, or credentials.
This does not automatically pick one of several conflicting EPG records.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

from catalog_audit import index_catalog, parse_playlist
from guide_coverage import parse_xmltv_time
from native_epg_overlay import proposed_links
from source_comparison import scan_xmltv


PLACEHOLDER_TITLES = {
    "no information", "no info", "no programme information",
    "no program information", "to be announced", "tba",
    "programme information unavailable", "program information unavailable",
}


def canonical_title(title: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def classify(titles: set[str]) -> str:
    """Classify a collision, never choose a winning schedule."""
    if len(titles) < 2:
        return "not_a_conflict"
    folded = {canonical_title(t) for t in titles}
    if len(folded) == 1:
        return "case_or_spacing_only"
    if len({re.sub(r"[^\w]+", "", t) for t in folded}) == 1:
        return "punctuation_only"
    if folded <= PLACEHOLDER_TITLES:
        return "only_placeholders"
    if folded & PLACEHOLDER_TITLES:
        return "placeholder_and_real_title"
    return "substantive_title_conflict"


def audit(source: Path, wanted_ids: set[str], *,
          begin: datetime, end: datetime) -> dict:
    opener = gzip.open if source.name.lower().endswith(".gz") else open
    slots: dict[tuple[str, datetime, datetime], set[str]] = defaultdict(set)
    stats: Counter[str] = Counter()
    with opener(source, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty XMLTV guide") from exc
        if root.tag != "tv":
            raise ValueError("Expected XMLTV root <tv>")
        for event, elem in context:
            if event != "end":
                continue
            if elem.tag == "programme":
                source_id = elem.get("channel", "").strip()
                if source_id in wanted_ids:
                    start = parse_xmltv_time(elem.get("start", ""))
                    stop = parse_xmltv_time(elem.get("stop", ""))
                    if (start is not None and stop is not None and stop > start
                            and start < end and stop > begin):
                        title = (elem.findtext("title") or "").strip()
                        if title:
                            slots[(source_id, start, stop)].add(title)
                            stats["valid_programme_records"] += 1
                root.clear()
            elif elem.tag == "channel":
                root.clear()
    classifications: Counter[str] = Counter()
    sources_by_type: dict[str, set[str]] = defaultdict(set)
    all_conflict_sources: set[str] = set()
    for (source_id, _, _), titles in slots.items():
        kind = classify(titles)
        if kind == "not_a_conflict":
            continue
        classifications[kind] += 1
        sources_by_type[kind].add(source_id)
        all_conflict_sources.add(source_id)
    trivial = (sources_by_type["case_or_spacing_only"]
               | sources_by_type["punctuation_only"])
    unsafe = (sources_by_type["only_placeholders"]
              | sources_by_type["placeholder_and_real_title"]
              | sources_by_type["substantive_title_conflict"])
    return {
        "status": "private_conflict_characterization_only",
        "candidate_source_ids": len(wanted_ids),
        "unique_time_slots": len(slots),
        "programme_records": stats["valid_programme_records"],
        "conflicting_time_slots": sum(classifications.values()),
        "collisions_by_type": dict(classifications),
        "source_ids_with_any_collision": len(all_conflict_sources),
        "source_ids_with_only_trivial_title_variants": len(trivial - unsafe),
        "source_ids_with_nontrivial_collisions": len(unsafe),
        "programme_titles_and_channel_ids_not_exposed": True,
        "automatic_conflict_resolution_approved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()
    if not 1 <= args.hours <= 48:
        parser.error("Window must be 1–48 hours")
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=args.hours)
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    catalog = index_catalog(args.catalog.read_text(encoding="utf-8"))
    baseline_ids = set(scan_xmltv(args.baseline, set(), begin=now, end=end)["declared"])
    links, _ = proposed_links(playlist, catalog, baseline_ids)
    print(json.dumps(audit(args.native, {v["source_id"] for v in links.values()},
                           begin=now, end=end), indent=2))


if __name__ == "__main__":
    main()
