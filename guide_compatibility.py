#!/usr/bin/env python3
"""Read-only XMLTV vs private M3U identifier compatibility diagnostics.

Only local file paths are accepted. The tool never contacts streams, stores
M3U URLs, edits channel IDs, or republishes third-party programme listings.
The report distinguishes exact EPG-ID matches from *unapproved* case-only
candidates, which should never be treated as working TiviMate assignments.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from catalog_audit import parse_playlist


def channel_ids_from_xmltv(path: Path) -> list[str]:
    """Stream XMLTV channel IDs, stopping at the first programme for speed.

    XMLTV guides normally list channel declarations before programme records.
    The report explicitly notes this scope; no programme or source URL is read
    into memory. Files may be plain .xml or gzip-compressed .xml.gz.
    """
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    with opener(path, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty or malformed XMLTV document") from exc
        if root.tag != "tv":
            raise ValueError("Expected an XMLTV <tv> root element")
        ids = []
        for action, elem in context:
            if action == "start" and elem.tag == "programme":
                break
            if action == "end" and elem.tag == "channel":
                channel_id = elem.get("id", "").strip()
                if channel_id:
                    ids.append(channel_id)
                root.clear()
        return ids


def compatibility_report(playlist: list[dict], guide_ids: list[str]) -> dict:
    """Evaluate matching potential without asserting broadcaster identity."""
    existing = [e["channel_id"] for e in playlist
                if e["channel_id"] and not e["channel_id"].casefold().startswith("dummy-")]
    original = Counter(existing)
    guide = Counter(guide_ids)
    folded_guide: dict[str, set[str]] = defaultdict(set)
    for guide_id in guide:
        folded_guide[guide_id.casefold()].add(guide_id)

    exact = {key for key in original if key in guide}
    case_only = {
        key for key in original
        if key not in guide and len(folded_guide.get(key.casefold(), set())) == 1
    }
    ambiguous = {
        key for key in original
        if key not in guide and len(folded_guide.get(key.casefold(), set())) > 1
    }
    unmatched = set(original) - exact - case_only - ambiguous
    return {
        "status": "read_only_compatibility_not_live_stream_verification",
        "main_playlist_channels": len(playlist),
        "distinct_nonplaceholder_main_ids": len(original),
        "xmltv_declared_channels": sum(guide.values()),
        "xmltv_distinct_ids": len(guide),
        "exact_id_matches": len(exact),
        "exact_match_playlist_channels": sum(original[x] for x in exact),
        "case_only_candidates_not_automatically_assigned": len(case_only),
        "case_only_candidate_playlist_channels": sum(original[x] for x in case_only),
        "ambiguous_casefold_candidates": len(ambiguous),
        "unmatched_main_ids": len(unmatched),
        "guide_repeated_exact_ids": sum(count > 1 for count in guide.values()),
        "inspection_scope": "channel_declarations_before_first_programme",
        "playlist_and_guide_unchanged": True,
        "ready_to_replace_existing_epg": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path,
                        help="Local private M3U; stream URLs are discarded")
    parser.add_argument("--guide", required=True, type=Path,
                        help="Local XMLTV .xml or .xml.gz; no network requests")
    args = parser.parse_args()
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    report = compatibility_report(playlist, channel_ids_from_xmltv(args.guide))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
