#!/usr/bin/env python3
"""Build a PRIVATE, read-only Eagle channel inventory from an existing M3U.

The output preserves Main's channel names, groups, and exact tvg-id values.
It never includes stream URLs, authentication material, stream IDs, imported
programme listings, or proposed/approved network identities.  In particular,
an exact match in the comparison guide is not proof of broadcaster identity.

Keep the generated registry OUTSIDE the public source repository.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from catalog_audit import parse_playlist
from guide_compatibility import channel_ids_from_xmltv


def is_placeholder(channel_id: str) -> bool:
    return not channel_id or channel_id.casefold().startswith("dummy-")


def registry_from_entries(entries: list[dict], guide_ids: list[str] | None = None,
                          *, created_utc: str | None = None) -> dict:
    """Return private M3U metadata with no assumption of verified channels."""
    counts = Counter(e["channel_id"].casefold() for e in entries
                     if not is_placeholder(e["channel_id"]))
    baseline = set(guide_ids) if guide_ids is not None else None
    status_counts: Counter[str] = Counter()
    rows = []
    for ordinal, entry in enumerate(entries, 1):
        channel_id = entry["channel_id"]
        if is_placeholder(channel_id):
            epg_status = "placeholder_or_missing"
        elif baseline is None:
            epg_status = "baseline_not_evaluated"
        elif channel_id in baseline:
            epg_status = "baseline_exact_match"
        else:
            epg_status = "baseline_no_exact_match"
        status_counts[epg_status] += 1
        rows.append({
            "ordinal": ordinal,
            "display_name": entry["name"],
            "group": entry["group"],
            "tvg_id": channel_id,
            "epg_status": epg_status,
            "shared_id_entries": counts.get(channel_id.casefold(), 0),
            "network_identity": "unverified",
            "programme_source": "not_assigned",
            "approved_for_public_guide": False,
        })

    return {
        "schema_version": 1,
        "created_utc": created_utc or datetime.now(timezone.utc).isoformat(),
        "purpose": "private_eagle_epg_replacement_inventory",
        "privacy": {
            "no_stream_urls": True,
            "no_stream_ids": True,
            "no_programme_titles_or_source_data": True,
            "do_not_publish": True,
        },
        "summary": {
            "channel_entries": len(rows),
            "distinct_real_tvg_ids": len(counts),
            "shared_real_tvg_ids": sum(number > 1 for number in counts.values()),
            "entries_with_shared_real_tvg_id": sum(number for number in counts.values()
                                                    if number > 1),
            "baseline_checked": baseline is not None,
            "epg_status_counts": dict(sorted(status_counts.items())),
            "individually_verified_channels": 0,
            "approved_programme_sources": 0,
            "ready_to_replace_existing_epg": False,
        },
        "channels": rows,
    }


def write_private_registry(output_path: Path, registry: dict) -> None:
    """Refuse any path inside public project; write a private atomic JSON file."""
    output = output_path.resolve()
    public_project = Path(__file__).resolve().parent
    if output.is_relative_to(public_project):
        raise ValueError("Private channel registries must be stored outside the public repository")
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=output.parent, prefix=".eagle-registry-",
                                         suffix=".json", delete=False) as handle:
            staged = Path(handle.name)
            os.chmod(staged, 0o600)
            json.dump(registry, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        staged.replace(output)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", type=Path, required=True,
                        help="Existing private M3U; never modified")
    parser.add_argument("--baseline-guide", type=Path,
                        help="Optional local XMLTV .xml/.xml.gz, read-only ID benchmark")
    parser.add_argument("--output", type=Path, required=True,
                        help="Private JSON location OUTSIDE public repository")
    args = parser.parse_args()
    entries = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    ids = channel_ids_from_xmltv(args.baseline_guide) if args.baseline_guide else None
    registry = registry_from_entries(entries, ids)
    write_private_registry(args.output, registry)
    print(json.dumps({
        "status": "private_inventory_written",
        "summary": registry["summary"],
        "main_playlist_and_guide_unchanged": True,
        "no_broadcasters_or_programmes_verified": True,
    }, indent=2))


if __name__ == "__main__":
    main()
