#!/usr/bin/env python3
"""Privately compare two Eagle XMLTV snapshots at the SAME UTC instant.

Only aggregate strict-candidate counts and differences are printed. Source
XMLTV files, channel IDs, programme titles, playlist data and credentials are
never included in the report. This does not authorize an EPG publication.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import filecmp
import json
from pathlib import Path

from catalog_audit import index_catalog, parse_playlist
from schedule_horizon_audit import DEFAULT_HOURS, audit_horizons, parse_as_of


def compare_snapshots(playlist: list[dict], catalog: dict[str, dict], *,
                      baseline: Path, older: Path, newer: Path,
                      as_of: datetime,
                      hours: tuple[int, ...] = DEFAULT_HOURS) -> dict:
    """Compare independent horizon audits, without returning source details."""
    if older.resolve() == newer.resolve():
        raise ValueError("Old and fresh snapshots must be different file paths")
    identical = filecmp.cmp(older, newer, shallow=False)
    old_report = audit_horizons(
        playlist, catalog, baseline=baseline, eagle=older,
        as_of=as_of, hours=hours,
    )
    new_report = audit_horizons(
        playlist, catalog, baseline=baseline, eagle=newer,
        as_of=as_of, hours=hours,
    )
    rows = []
    for before, after in zip(old_report["window_results"],
                             new_report["window_results"], strict=True):
        before_rejections = before["rejection_counts"]
        after_rejections = after["rejection_counts"]
        rejection_keys = sorted(set(before_rejections) | set(after_rejections))
        rows.append({
            "hours": before["hours"],
            "old_candidate_channels": before["candidate_channels"],
            "fresh_candidate_channels": after["candidate_channels"],
            "candidate_channel_change": (
                after["candidate_channels"] - before["candidate_channels"]
            ),
            "old_candidate_programmes": before["candidate_programmes"],
            "fresh_candidate_programmes": after["candidate_programmes"],
            "candidate_programme_change": (
                after["candidate_programmes"] - before["candidate_programmes"]
            ),
            "rejection_count_changes": {
                reason: after_rejections.get(reason, 0)
                - before_rejections.get(reason, 0)
                for reason in rejection_keys
            },
        })
    return {
        "status": "private_unapproved_schedule_refresh_comparison",
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "snapshots_binary_identical": identical,
        "window_results": rows,
        "interpretation": (
            "Positive candidate changes support that new data is available, "
            "but do not establish the provider refresh cadence, live stream "
            "identity, schedule accuracy or redistribution rights. A fixed "
            "instant prevents observation-time drift from distorting results."
        ),
        "private_inputs_unchanged": True,
        "no_source_or_channel_details_in_report": True,
        "actual_stream_verified": False,
        "redistribution_rights_verified": False,
        "approved_for_public_guide": False,
        "ready_to_replace_epg41": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--old-native", required=True, type=Path)
    parser.add_argument("--fresh-native", required=True, type=Path)
    parser.add_argument("--as-of", type=str,
                        help="Optional ISO-8601 instant; default is current UTC")
    args = parser.parse_args()
    try:
        reference = parse_as_of(args.as_of) if args.as_of else datetime.now(timezone.utc)
        playlist = parse_playlist(
            args.playlist.read_text(encoding="utf-8-sig", errors="replace")
        )
        catalog = index_catalog(args.catalog.read_text(encoding="utf-8"))
        report = compare_snapshots(
            playlist, catalog, baseline=args.baseline, older=args.old_native,
            newer=args.fresh_native, as_of=reference,
        )
    except (OSError, ValueError) as exc:
        # Do not include OS exception text: it can disclose private file paths.
        parser.error(type(exc).__name__ + ": invalid private input or snapshots")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
