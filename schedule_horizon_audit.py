#!/usr/bin/env python3
"""Measure the shrinking usable horizon of a PRIVATE Eagle XMLTV snapshot.

Runs the existing strict, unapproved overlay checks at several future windows
from one fixed reference instant. Only aggregate counts leave the process: no
channel IDs, programme titles, stream links, credentials or guide copies.

This is a read-only diagnostic, never a publisher or a TiviMate EPG updater.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from catalog_audit import index_catalog, parse_playlist
from native_epg_overlay import build_candidate


DEFAULT_HOURS = (6, 12, 18, 24, 36, 48)


def parse_as_of(raw: str) -> datetime:
    """Require an explicit timezone when comparing historical snapshots."""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--as-of must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include a timezone")
    return parsed.astimezone(timezone.utc)


def audit_horizons(playlist: list[dict], catalog: dict[str, dict], *,
                   baseline: Path, eagle: Path, as_of: datetime,
                   hours: tuple[int, ...] = DEFAULT_HOURS) -> dict:
    """Apply exactly the same conservative selection policy at each horizon."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Reference instant must be timezone-aware")
    if not hours or any(h < 1 or h > 48 for h in hours):
        raise ValueError("Horizon hours must be between 1 and 48")
    if list(hours) != sorted(set(hours)):
        raise ValueError("Horizon hours must be unique and increasing")

    rows = []
    for horizon in hours:
        _, report = build_candidate(
            playlist, catalog, baseline=baseline, eagle=eagle,
            now=as_of, hours=horizon,
        )
        rows.append({
            "hours": horizon,
            "candidate_channels": report["candidate_channels"],
            "candidate_programmes": report["candidate_programmes"],
            "rejection_counts": report["selection_counts"],
        })
    return {
        "status": "private_unapproved_schedule_horizon_audit",
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "window_results": rows,
        "interpretation": (
            "Counts are strict candidates in independent rolling windows; a "
            "shorter-window match is not evidence of a complete 48-hour EPG. "
            "Compare snapshots taken at different times to assess freshness."
        ),
        "no_programme_or_channel_details_in_report": True,
        "playlist_and_sources_unchanged": True,
        "stream_identities_verified": False,
        "redistribution_rights_verified": False,
        "approved_for_public_guide": False,
        "ready_to_replace_epg41": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--native", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--as-of", type=str,
                        help="Optional ISO-8601 instant; default is current UTC")
    args = parser.parse_args()
    try:
        reference = parse_as_of(args.as_of) if args.as_of else datetime.now(timezone.utc)
        playlist = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
        catalog = index_catalog(args.catalog.read_text(encoding="utf-8"))
        result = audit_horizons(
            playlist, catalog, baseline=args.baseline, eagle=args.native,
            as_of=reference,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
