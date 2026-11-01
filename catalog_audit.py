#!/usr/bin/env python3
"""Read-only, privacy-conscious comparison of an M3U and IPTV channel catalog.

This reports candidate guide IDs but does NOT verify a broadcaster, change a
playlist, access a stream or produce public XMLTV programme entries. Input
files must stay private: stream URLs may contain live account credentials.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


ATTRIBUTE_RE = re.compile(r"([\w-]+)\s*=\s*([\"'])(.*?)\2")
STREAM_TAIL_RE = re.compile(r"^([0-9]+)\.(?:m3u8|ts)$", re.IGNORECASE)
SLOT_RE = re.compile(r"^NHL Event\s+0*([1-9][0-9]*)$", re.IGNORECASE)
PROVIDER_SLOT_RE = re.compile(r"^NHL\s*\|\s*0*([1-9][0-9]*)\s*-\s*(.*)$", re.IGNORECASE)
GAME_HINT_RE = re.compile(r"^(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(.+?)\s+@\s+(.+)$", re.IGNORECASE)
EASTERN = ZoneInfo("America/New_York")


def split_extinf(header: str) -> tuple[str, str]:
    """Split on the first comma not inside a quoted attribute value."""
    quote = None
    for index, char in enumerate(header):
        if char in ("'", '"'):
            if quote is None:
                quote = char
            elif quote == char:
                quote = None
        elif char == "," and quote is None:
            return header[:index], header[index + 1 :].strip()
    raise ValueError("Malformed EXTINF record: no channel-name separator")


def numeric_stream_id(url: str) -> str | None:
    """Extract only a terminal numeric ID; never retain or report an URL."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None
    tail = parts.path.rsplit("/", 1)[-1]
    match = STREAM_TAIL_RE.fullmatch(tail)
    return match.group(1) if match else None


def parse_playlist(contents: str) -> list[dict]:
    """Return non-secret metadata from M3U; discard every media URL."""
    lines = contents.splitlines()
    entries = []
    for index, line in enumerate(lines):
        if not line.startswith("#EXTINF"):
            continue
        prefix, name = split_extinf(line)
        attrs = {key.lower(): value for key, _, value in ATTRIBUTE_RE.findall(prefix)}
        url = lines[index + 1].strip() if index + 1 < len(lines) else ""
        try:
            hls = urlsplit(url).path.lower().endswith(".m3u8")
        except ValueError:
            hls = False
        entries.append({
            "name": name,
            "channel_id": attrs.get("tvg-id", "").strip(),
            "group": attrs.get("group-title", "").strip(),
            "stream_id": numeric_stream_id(url),
            "hls": hls,
        })
    return entries


def index_catalog(contents: str) -> dict[str, dict]:
    """Retain only names and EPG IDs; ignore icons, URLs and other fields."""
    raw = json.loads(contents)
    if not isinstance(raw, list):
        raise ValueError("Catalog must be a list")
    records = {}
    for channel in raw:
        if not isinstance(channel, dict):
            raise ValueError("Catalog entries must be objects")
        sid = str(channel.get("stream_id") or "")
        if not sid.isdecimal() or int(sid) <= 0 or sid in records:
            raise ValueError("Catalog stream IDs must be unique positive integers")
        records[sid] = {
            "name": str(channel.get("name") or ""),
            "epg_id": str(channel.get("epg_channel_id") or ""),
        }
    return records


def audit(playlist: list[dict], catalog: dict[str, dict]) -> dict:
    counts: Counter[str] = Counter()
    dynamic_events = []
    for entry in playlist:
        counts["playlist_channels"] += 1
        if entry["hls"]:
            counts["hls_channels"] += 1
        if entry["channel_id"]:
            counts["channels_with_epg_id"] += 1
        if entry["channel_id"].lower().startswith("dummy-"):
            counts["placeholder_epg_id"] += 1

        sid = entry["stream_id"]
        if sid is None or sid not in catalog:
            counts["unmatched_stream_id"] += 1
            continue
        counts["provider_stream_id_matched"] += 1
        provider = catalog[sid]
        custom_id = entry["channel_id"]
        provider_id = provider["epg_id"]
        if not custom_id:
            counts["playlist_epg_id_missing"] += 1
        elif not provider_id:
            counts["provider_epg_id_missing"] += 1
        elif custom_id.casefold() == provider_id.casefold():
            counts["epg_ids_agree"] += 1
        else:
            counts["epg_ids_differ"] += 1

        slot = SLOT_RE.fullmatch(entry["name"])
        provider_slot = PROVIDER_SLOT_RE.fullmatch(provider["name"])
        if slot is not None:
            hint = provider_slot.group(2).strip() if (provider_slot and slot.group(1) == provider_slot.group(1)) else ""
            dynamic_events.append({
                "playlist_name": entry["name"],
                "channel_id": custom_id,
                "stream_id": sid,
                "provider_label_hint": hint,
                "requires_live_verification": True,
                "publishable_as_epg": False,
            })

    result = {
        "version": 1,
        "status": "diagnostic_only_not_for_publication",
        "counts": dict(sorted(counts.items())),
        "nhl_event_candidates": dynamic_events,
        "notes": [
            "EPG IDs from Main must remain unchanged to protect existing assignments.",
            "Disagreement with provider EPG IDs does not prove the custom ID is wrong.",
            "Provider event labels are unverified hints, not proof of on-air content.",
            "Do not turn candidates into XMLTV programmes without verified schedule and broadcaster identity.",
        ],
    }
    return result


def annotate_nhl_schedule(report: dict, response: dict, eastern_day: str) -> dict:
    """Match provider *hints* to NHL start times; never assert stream content.

    The public NHL schedule identifies games, not which IPTV event slot airs
    them. An exact schedule match therefore stays non-publishable until someone
    separately verifies that the stream really carries the programme.
    """
    target_day = date.fromisoformat(eastern_day)
    if not isinstance(response, dict) or not isinstance(response.get("gameWeek"), list):
        raise ValueError("Expected an NHL schedule with gameWeek")
    official_games = []
    for day in response["gameWeek"]:
        if not isinstance(day, dict) or not isinstance(day.get("games"), list):
            continue
        for game in day["games"]:
            if not isinstance(game, dict):
                continue
            try:
                away = game["awayTeam"]["commonName"]["default"]
                home = game["homeTeam"]["commonName"]["default"]
                stamp = datetime.fromisoformat(game["startTimeUTC"].replace("Z", "+00:00"))
                game_id = game["id"]
                if (not isinstance(away, str) or not isinstance(home, str)
                        or stamp.tzinfo is None or type(game_id) is not int):
                    continue
                local = stamp.astimezone(EASTERN)
                if local.date() == target_day:
                    official_games.append((away.casefold(), home.casefold(), local, stamp, game_id))
            except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
                continue

    for candidate in report["nhl_event_candidates"]:
        candidate["official_schedule_match"] = False
        match = GAME_HINT_RE.fullmatch(candidate["provider_label_hint"])
        if match is None:
            continue
        try:
            time_string = re.sub(r"\s+", "", match.group(1)).upper()
            fmt = "%I:%M%p" if ":" in time_string else "%I%p"
            claimed_time = datetime.strptime(time_string, fmt).time()
        except ValueError:
            continue
        matches = [
            (utc_start, game_id)
            for away, home, local, utc_start, game_id in official_games
            if (away == match.group(2).strip().casefold()
                and home == match.group(3).strip().casefold()
                and local.hour == claimed_time.hour and local.minute == claimed_time.minute)
        ]
        if len(matches) != 1:
            continue
        utc_start, game_id = matches[0]
        candidate["official_schedule_match"] = True
        candidate["scheduled_start_utc"] = utc_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        candidate["nhl_game_id"] = game_id
        # Do not promote a scheduled NHL game into proof of IPTV stream identity.
        candidate["publishable_as_epg"] = False
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playlist", type=Path, required=True, help="Private M3U file to inspect")
    parser.add_argument("--catalog", type=Path, required=True, help="Private live_streams.json")
    parser.add_argument("--nhl-schedule", type=Path, help="Optional private copy of NHL schedule API JSON")
    parser.add_argument("--nhl-day", help="Eastern calendar date YYYY-MM-DD for schedule matching")
    args = parser.parse_args()
    entries = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    records = index_catalog(args.catalog.read_text(encoding="utf-8"))
    report = audit(entries, records)
    if args.nhl_schedule is not None:
        if not args.nhl_day:
            parser.error("--nhl-day is required when --nhl-schedule is supplied")
        response = json.loads(args.nhl_schedule.read_text(encoding="utf-8"))
        annotate_nhl_schedule(report, response, args.nhl_day)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
