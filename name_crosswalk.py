#!/usr/bin/env python3
"""Private, read-only name-based XMLTV crosswalk *preflight* for Eagle.

Only counts potential name matches. Neither a name match nor a shared ID
verifies that an IPTV stream carries that broadcaster, or grants permission
to republish an external listing. The output excludes private names/IDs.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

from catalog_audit import parse_playlist


QUALITY_SUFFIX = re.compile(r"(?:\s+(?:sd|hd|fhd|uhd|4k|720p|1080p|2160p))+$")
NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_name(name: str, *, quality: bool = False) -> str:
    value = unicodedata.normalize("NFKC", name).casefold()
    value = NON_WORD.sub(" ", value).strip()
    value = re.sub(r"\s+", " ", value)
    if quality:
        value = QUALITY_SUFFIX.sub("", value).strip()
    return value


def guide_names(path: Path) -> dict[str, set[str]]:
    """Stream over channels; ignore and discard all programme elements."""
    opened = gzip.open if path.name.lower().endswith(".gz") else open
    aliases: dict[str, set[str]] = defaultdict(set)
    with opened(path, "rb") as stream:
        context = ET.iterparse(stream, events=("start", "end"))
        try:
            _, root = next(context)
        except (StopIteration, ET.ParseError) as exc:
            raise ValueError("Empty or malformed XMLTV") from exc
        if root.tag != "tv":
            raise ValueError("Expected XMLTV root <tv>")
        for event, elem in context:
            if event != "end":
                continue
            if elem.tag == "channel":
                identifier = (elem.get("id") or "").strip()
                if identifier:
                    for alias in elem.findall("display-name"):
                        if alias.text and alias.text.strip():
                            aliases[identifier].add(alias.text.strip())
                root.clear()
            elif elem.tag == "programme":
                root.clear()
    return dict(aliases)


def summarize(playlist: list[dict], aliases: dict[str, set[str]]) -> dict:
    """Never output actual channel IDs, names, or schedule contents."""
    by_id: dict[str, set[str]] = defaultdict(set)
    for item in playlist:
        identifier = item.get("channel_id", "")
        if identifier and not identifier.casefold().startswith("dummy-"):
            by_id[identifier].add(item.get("name", ""))

    exact_index: dict[str, set[str]] = defaultdict(set)
    quality_index: dict[str, set[str]] = defaultdict(set)
    for guide_id, names in aliases.items():
        for name in names:
            exact_index[normalize_name(name)].add(guide_id)
            quality_index[normalize_name(name, quality=True)].add(guide_id)

    totals: Counter[str] = Counter()
    for eagle_id, eagle_names in by_id.items():
        direct = {eagle_id} if eagle_id in aliases else set()
        if direct:
            totals["existing_exact_id"] += 1
            continue
        exact = set().union(*(exact_index.get(normalize_name(name), set())
                              for name in eagle_names))
        if len(exact) == 1:
            totals["single_exact_name_hint"] += 1
        elif len(exact) > 1:
            totals["ambiguous_exact_name_hints"] += 1
        else:
            quality = set().union(*(quality_index.get(normalize_name(name, quality=True), set())
                                    for name in eagle_names))
            if len(quality) == 1:
                totals["single_quality_suffix_hint"] += 1
            elif len(quality) > 1:
                totals["ambiguous_quality_suffix_hints"] += 1
            else:
                totals["no_name_hint"] += 1

    return {
        "status": "private_crosswalk_preflight_only_not_stream_verification",
        "eagle_distinct_nonplaceholder_ids": len(by_id),
        "guide_ids_with_display_names": len(aliases),
        **{key: totals[key] for key in (
            "existing_exact_id", "single_exact_name_hint",
            "ambiguous_exact_name_hints", "single_quality_suffix_hint",
            "ambiguous_quality_suffix_hints", "no_name_hint")},
        "all_name_hints_require_manual_stream_identity_verification": True,
        "redistribution_rights_verified": False,
        "approved_mappings": 0,
        "safe_to_replace_existing_guide": False,
        "inputs_unchanged": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--guide", required=True, type=Path)
    args = parser.parse_args()
    playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    print(json.dumps(summarize(playlist, guide_names(args.guide)), indent=2))


if __name__ == "__main__":
    main()
