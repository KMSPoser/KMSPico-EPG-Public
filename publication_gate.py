#!/usr/bin/env python3
"""Fail-closed structural and privacy checks for the public XMLTV artifact.

This validates only the original verified supplement, never a provider guide.
An empty but valid supplement remains explicitly *not ready* for TiviMate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


MAX_XML_BYTES = 15_000_000
MAX_REPORT_BYTES = 20_000
SECRET_LIKE = re.compile(
    r"(?:https?://|(?:username|password|access_token|api_key|token)=|/live/|/movie/|/series/)",
    re.IGNORECASE,
)


def check_publication(guide: Path, coverage: Path) -> dict:
    if guide.stat().st_size > MAX_XML_BYTES or coverage.stat().st_size > MAX_REPORT_BYTES:
        raise ValueError("oversized_public_output")
    report = json.loads(coverage.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("kind") != "verified-supplement-only":
        raise ValueError("unapproved_public_source_kind")
    for key in ("channels", "programmes", "tvmaze_programmes"):
        if type(report.get(key)) is not int or report[key] < 0:
            raise ValueError("invalid_public_coverage_count")
    if report["tvmaze_programmes"] > report["programmes"]:
        raise ValueError("invalid_tvmaze_count")
    now = datetime.fromisoformat(report["generated_utc"])
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        raise ValueError("invalid_generation_time")

    root = ET.parse(guide).getroot()
    if (root.tag != "tv" or root.attrib != {
        "generator-info-name": "KMSPico verified EPG supplement"
    }):
        raise ValueError("not_original_verified_supplement")

    channels: set[str] = set()
    programme_counts: dict[str, int] = {}
    intervals: dict[str, list[tuple[datetime, datetime]]] = {}
    for child in root:
        if child.tag == "channel":
            if set(child.attrib) != {"id"} or len(child) != 1 or child[0].tag != "display-name":
                raise ValueError("unexpected_channel_content")
            channel_id = child.get("id", "")
            name = child.findtext("display-name", "")
            if not channel_id or channel_id in channels or not name.strip():
                raise ValueError("invalid_or_duplicate_channel")
            if SECRET_LIKE.search(channel_id) or SECRET_LIKE.search(name):
                raise ValueError("credential_like_public_channel")
            channels.add(channel_id)
        elif child.tag == "programme":
            if set(child.attrib) != {"channel", "start", "stop"}:
                raise ValueError("unexpected_programme_attributes")
            if [node.tag for node in child] != ["title", "desc"]:
                raise ValueError("unexpected_programme_content")
            if any(node.attrib != {"lang": "en"} for node in child):
                raise ValueError("unexpected_programme_language")
            channel_id = child.get("channel", "")
            title, description = child[0].text or "", child[1].text or ""
            if not title.strip() or not description.strip():
                raise ValueError("missing_programme_text")
            if SECRET_LIKE.search(title) or SECRET_LIKE.search(description):
                raise ValueError("credential_like_public_programme")
            try:
                start = datetime.strptime(child.attrib["start"], "%Y%m%d%H%M%S %z")
                stop = datetime.strptime(child.attrib["stop"], "%Y%m%d%H%M%S %z")
            except ValueError as exc:
                raise ValueError("invalid_programme_timestamp") from exc
            if stop <= start or start.utcoffset() != timezone.utc.utcoffset(start) or stop.utcoffset() != timezone.utc.utcoffset(stop):
                raise ValueError("invalid_programme_interval")
            if description not in (
                "Operator-verified schedule entry",
                "Schedule data: TVmaze (CC BY-SA 4.0); broadcaster identity operator-confirmed",
            ):
                raise ValueError("unapproved_programme_provenance")
            programme_counts[channel_id] = programme_counts.get(channel_id, 0) + 1
            intervals.setdefault(channel_id, []).append((start, stop))
        else:
            raise ValueError("unexpected_public_xmltv_element")

    if not set(programme_counts).issubset(channels):
        raise ValueError("orphan_public_programme")
    if (len(channels) != report["channels"]
            or sum(programme_counts.values()) != report["programmes"]):
        raise ValueError("public_counts_do_not_match")
    if channels != set(programme_counts):
        raise ValueError("channels_without_programmes")
    for segments in intervals.values():
        segments.sort()
        if any(a[1] > b[0] for a, b in zip(segments, segments[1:])):
            raise ValueError("overlapping_public_programmes")

    return {
        "publication_checked": True,
        "status": "supplement_populated" if programme_counts else "empty_awaiting_verified_sources",
        "channels": len(channels),
        "programmes": sum(programme_counts.values()),
        "main_playlist_untouched": True,
        "private_provider_data_included": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guide", type=Path, default=Path("docs/guide.xml"))
    parser.add_argument("--coverage", type=Path, default=Path("docs/coverage.json"))
    args = parser.parse_args()
    print(json.dumps(check_publication(args.guide, args.coverage), indent=2))


if __name__ == "__main__":
    main()
