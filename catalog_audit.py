#!/usr/bin/env python3
"""Read-only, privacy-conscious comparison of an M3U and IPTV channel catalog.

This reports candidate guide IDs but does NOT verify a broadcaster, change a
playlist, access a stream or produce public XMLTV programme entries. Input
files must stay private: stream URLs may contain live account credentials.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from tvmaze_source import channel_mappings, fetch_us_schedule


ATTRIBUTE_RE = re.compile(r"([\w-]+)\s*=\s*([\"'])(.*?)\2")
STREAM_TAIL_RE = re.compile(r"^([0-9]+)\.(?:m3u8|ts)$", re.IGNORECASE)
SLOT_RE = re.compile(r"^NHL Event\s+0*([1-9][0-9]*)$", re.IGNORECASE)
PROVIDER_SLOT_RE = re.compile(r"^NHL\s*\|\s*0*([1-9][0-9]*)\s*-\s*(.*)$", re.IGNORECASE)
GAME_HINT_RE = re.compile(r"^(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s+(.+?)\s+@\s+(.+)$", re.IGNORECASE)
EASTERN = ZoneInfo("America/New_York")
# These are merely convenient starting points for a human to inspect in TiviMate.
# Never treat a matching name, country suffix, or provider EPG ID as proof of
# which network an IPTV stream actually carries.
PILOT_REVIEW_NAMES = (
    "PBS Kids", "HGTV", "Food Network", "Animal Planet", "AMC", "FX",
    "Comedy Central", "ESPN", "CNN", "ABC News Live",
)


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


def shared_epg_ids(playlist: list[dict]) -> dict[str, int]:
    """Count reused real guide IDs, case-insensitively, without changing them."""
    counts = Counter(
        entry["channel_id"].casefold() for entry in playlist
        if entry["channel_id"] and not entry["channel_id"].casefold().startswith("dummy-")
    )
    return {channel_id: count for channel_id, count in counts.items() if count > 1}


def pilot_review_queue(playlist: list[dict], catalog: dict[str, dict]) -> list[dict]:
    """Suggest only low-ambiguity US channels for *human* identity checking.

    No selection can verify an IPTV stream or approve an EPG mapping. A channel
    is omitted from this starter queue if its current ID is reused, absent,
    differs from the provider ID, or isn't one of the pilot names above.
    Those omitted channels are not necessarily incorrect.
    """
    repeated = shared_epg_ids(playlist)
    result = []
    for wanted in PILOT_REVIEW_NAMES:
        matches = []
        for entry in playlist:
            current_id = entry["channel_id"]
            if (entry["name"].casefold() != wanted.casefold()
                    or not current_id.casefold().endswith(".us")
                    or current_id.casefold() in repeated):
                continue
            provider = catalog.get(entry["stream_id"])
            if not provider or provider["epg_id"].casefold() != current_id.casefold():
                continue
            matches.append((entry, provider))
        if len(matches) != 1:
            continue  # Avoid ambiguous names even when their IDs are unique.
        entry, provider = matches[0]
        result.append({
            "playlist_name": entry["name"],
            "channel_id": entry["channel_id"],
            "group": entry["group"],
            "provider_label_hint": provider["name"],
            "epg_id_reused": False,
            "provider_epg_id_agrees": True,
            "requires_live_verification": True,
            "publishable_as_epg": False,
        })
    return result


def mapping_preflight(playlist: list[dict], catalog: dict[str, dict], config: dict) -> dict:
    """Check approved TVmaze IDs against private Main *without* editing either.

    This is a local structural check, NOT proof of which broadcaster a stream
    carries. It must never automatically set ``operator_verified`` or cause
    a mapping to be published. Channel IDs and names may be user-customized,
    so provider disagreements are warnings rather than automatic rewrites.
    """
    mappings = channel_mappings(config)
    by_id: dict[str, list[dict]] = {}
    for entry in playlist:
        by_id.setdefault(entry["channel_id"].casefold(), []).append(entry)

    blockers = []
    warnings = []
    for item in mappings:
        channel_id = item["channel_id"]
        key = channel_id.casefold()
        matches = by_id.get(key, [])
        if not matches:
            blockers.append({"channel_id": channel_id, "code": "not_in_main"})
            continue
        if len(matches) != 1:
            blockers.append({"channel_id": channel_id, "code": "shared_main_epg_id",
                             "matching_channels": len(matches)})
            continue
        if key.startswith("dummy-"):
            blockers.append({"channel_id": channel_id, "code": "placeholder_epg_id"})
            continue
        entry = matches[0]
        if channel_id != entry["channel_id"]:
            blockers.append({"channel_id": channel_id, "code": "exact_id_case_mismatch"})
        if item["channel_name"] != entry["name"]:
            warnings.append({"channel_id": channel_id, "code": "custom_display_name"})
        provider = catalog.get(entry["stream_id"])
        if provider is None:
            warnings.append({"channel_id": channel_id, "code": "no_provider_stream_match"})
        elif provider["epg_id"].casefold() != key:
            warnings.append({"channel_id": channel_id, "code": "provider_epg_id_differs"})

    return {
        "status": "private_structure_check_not_live_stream_verification",
        "checked_mappings": len(mappings),
        "blocking_issues": blockers,
        "warnings": warnings,
        "structurally_consistent": not blockers,
        "not_a_publication_approval": True,
    }


def annotate_tvmaze_discovery(report: dict, daily_schedules: list[list[dict]]) -> dict:
    """Attach *unapproved* network-ID hints from public TVmaze episode listings.

    A source network name matching an M3U label is still NOT evidence that
    the stream plays that network. Ambiguous identities are omitted entirely.
    This never toggles operator_verified or creates a published channel map.
    """
    observed: dict[str, dict[tuple[str, int, str], int]] = {}
    for day in daily_schedules:
        if not isinstance(day, list):
            raise ValueError("TVmaze schedules must contain episode lists")
        for episode in day:
            if not isinstance(episode, dict) or not isinstance(episode.get("show"), dict):
                continue
            show = episode["show"]
            kind = "network" if show.get("network") else "webChannel"
            network = show.get(kind)
            if not isinstance(network, dict):
                continue
            name, nid = network.get("name"), network.get("id")
            if not isinstance(name, str) or type(nid) is not int or nid <= 0:
                continue
            # Only count entries this project's TVmaze adapter could import.
            if (not isinstance(episode.get("runtime"), int) or isinstance(episode.get("runtime"), bool)
                    or not 1 <= episode["runtime"] <= 720
                    or not isinstance(episode.get("airstamp"), str)
                    or not isinstance(episode.get("url"), str)
                    or not episode["url"].startswith("https://www.tvmaze.com/episodes/")):
                continue
            try:
                air_time = datetime.fromisoformat(episode["airstamp"].replace("Z", "+00:00"))
                if air_time.tzinfo is None:
                    continue
            except ValueError:
                continue
            identity = (kind, nid, name)
            keys = observed.setdefault(name.casefold(), {})
            keys[identity] = keys.get(identity, 0) + 1

    for candidate in report["pilot_review_queue"]:
        candidate.pop("proposed_tvmaze_mapping", None)
        candidate.pop("tvmaze_episode_count_in_sample", None)
        matches = observed.get(candidate["playlist_name"].casefold(), {})
        candidate["tvmaze_discovery_status"] = "not_found_in_sample"
        if len(matches) != 1:
            if matches:
                candidate["tvmaze_discovery_status"] = "ambiguous_network_identity"
            continue
        (kind, network_id, network_name), count = next(iter(matches.items()))
        candidate["tvmaze_discovery_status"] = "candidate_needs_stream_verification"
        candidate["tvmaze_episode_count_in_sample"] = count
        candidate["proposed_tvmaze_mapping"] = {
            "channel_id": candidate["channel_id"],
            "channel_name": candidate["playlist_name"],
            "tvmaze_network_id": network_id,
            "tvmaze_network_name": network_name,
            "kind": kind,
            "operator_verified": False,
        }
        candidate["publishable_as_epg"] = False
    return report


def audit(playlist: list[dict], catalog: dict[str, dict]) -> dict:
    counts: Counter[str] = Counter()
    dynamic_events = []
    shared = shared_epg_ids(playlist)
    counts["shared_epg_id_values"] = len(shared)
    counts["channels_using_shared_epg_ids"] = sum(shared.values())
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
        "shared_epg_id_examples": [
            {"channel_id": channel_id, "entries": count}
            for channel_id, count in sorted(shared.items(), key=lambda value: (-value[1], value[0]))[:15]
        ],
        "pilot_review_queue": pilot_review_queue(playlist, catalog),
        "nhl_event_candidates": dynamic_events,
        "notes": [
            "EPG IDs from Main must remain unchanged to protect existing assignments.",
            "Repeated EPG IDs may be intentional for backup channels; never rewrite them automatically.",
            "Pilot review candidates still require actual stream verification and TVmaze network matching.",
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
    parser.add_argument("--tvmaze-discovery-days", type=int, default=0,
                        help="Optional 1-7 day public TVmaze schedule search; never uploads private data")
    parser.add_argument("--tvmaze-mapping-preflight", type=Path,
                        help="Optional local approved TVmaze map to check against Main, without edits")
    args = parser.parse_args()
    if not 0 <= args.tvmaze_discovery_days <= 7:
        parser.error("--tvmaze-discovery-days must be between 0 and 7")
    entries = parse_playlist(args.playlist.read_text(encoding="utf-8-sig", errors="replace"))
    records = index_catalog(args.catalog.read_text(encoding="utf-8"))
    report = audit(entries, records)
    if args.tvmaze_mapping_preflight is not None:
        mapping_config = json.loads(args.tvmaze_mapping_preflight.read_text(encoding="utf-8"))
        report["tvmaze_mapping_preflight"] = mapping_preflight(entries, records, mapping_config)
    if args.nhl_schedule is not None:
        if not args.nhl_day:
            parser.error("--nhl-day is required when --nhl-schedule is supplied")
        response = json.loads(args.nhl_schedule.read_text(encoding="utf-8"))
        annotate_nhl_schedule(report, response, args.nhl_day)
    if args.tvmaze_discovery_days:
        starting_day = datetime.now(EASTERN).date()
        dates = [(starting_day + timedelta(days=offset)).isoformat()
                 for offset in range(args.tvmaze_discovery_days)]
        annotate_tvmaze_discovery(report, [fetch_us_schedule(day) for day in dates])
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
