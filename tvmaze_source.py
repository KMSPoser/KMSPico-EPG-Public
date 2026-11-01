"""Import scheduled TV episodes from TVmaze for *explicitly verified* channels.

TVmaze's free data is CC BY-SA 4.0. This adapter deliberately uses only an
allowlist of exact TVmaze network IDs and user-confirmed XMLTV channel IDs; it
never guesses that an IPTV stream is showing a particular network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen


API_ROOT = "https://api.tvmaze.com/schedule?country=US&date="
MAX_RESPONSE_BYTES = 8_000_000


def channel_mappings(config: dict) -> list[dict]:
    if config.get("version") != 1 or not isinstance(config.get("channels"), list):
        raise ValueError("Unsupported TVmaze mapping configuration")
    result = []
    seen = set()
    networks = set()
    for item in config["channels"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid TVmaze channel mapping")
        for key in ("channel_id", "channel_name", "tvmaze_network_name"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"Missing channel mapping field: {key}")
        if type(item.get("tvmaze_network_id")) is not int or item["tvmaze_network_id"] <= 0:
            raise ValueError("TVmaze network ID must be a positive integer")
        if item.get("kind") not in ("network", "webChannel"):
            raise ValueError("A network or webChannel kind is required")
        if item.get("operator_verified") is not True:
            raise ValueError("Channel identity must be confirmed in the actual player")
        if item["channel_id"] in seen:
            raise ValueError("Each XMLTV channel may have only one TVmaze mapping")
        network_key = (item["kind"], item["tvmaze_network_id"])
        if network_key in networks:
            raise ValueError("A TVmaze network may not be assigned to multiple IPTV channels")
        networks.add(network_key)
        seen.add(item["channel_id"])
        result.append(item)
    return result


def fetch_us_schedule(day: str) -> list[dict]:
    # `day` must be our own ISO calendar date, never arbitrary external input.
    if datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day:
        raise ValueError("Invalid schedule date")
    request = Request(API_ROOT + day, headers={"User-Agent": "KMSPico-EPG/0.2"})
    with urlopen(request, timeout=15) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Oversized TVmaze schedule response")
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("Unexpected TVmaze schedule response")
    return payload


def events_from_schedule(episodes: list[dict], mappings: list[dict]) -> list[dict]:
    index = {(m["kind"], m["tvmaze_network_id"]): m for m in mappings}
    events = []
    for episode in episodes:
        if not isinstance(episode, dict) or not isinstance(episode.get("show"), dict):
            continue
        show = episode["show"]
        network_kind = "network" if show.get("network") else "webChannel"
        network = show.get(network_kind)
        if not isinstance(network, dict):
            continue
        mapping = index.get((network_kind, network.get("id")))
        # An ID alone is insufficient after a source rename or mapping mistake.
        if mapping is None or mapping["tvmaze_network_name"] != network.get("name"):
            continue
        try:
            start = datetime.fromisoformat(episode["airstamp"].replace("Z", "+00:00"))
            runtime = episode["runtime"]
            if start.tzinfo is None or type(runtime) is not int or not 1 <= runtime <= 720:
                continue
            stop = start + timedelta(minutes=runtime)
            name = show["name"]
            if not isinstance(name, str) or not name.strip():
                continue
            episode_name = episode.get("name")
            title = name if not isinstance(episode_name, str) or not episode_name.strip() else f"{name}: {episode_name}"
            url = episode.get("url")
            if not isinstance(url, str) or not url.startswith("https://www.tvmaze.com/episodes/"):
                continue
            events.append({
                "channel_id": mapping["channel_id"],
                "channel_name": mapping["channel_name"],
                "title": title,
                "start_utc": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "stop_utc": stop.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "verified_source_url": url,
                "source": "tvmaze",
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return events


def load_tvmaze_events(config_path: Path, now: datetime, fetcher=fetch_us_schedule) -> list[dict]:
    mappings = channel_mappings(json.loads(config_path.read_text(encoding="utf-8")))
    if not mappings:
        return []  # No network calls until a channel identity has been confirmed.
    events = []
    # A day's schedule can include local-time broadcasts crossing UTC midnight.
    for offset in range(-1, 7):
        date_string = (now.astimezone(timezone.utc).date() + timedelta(days=offset)).isoformat()
        events.extend(events_from_schedule(fetcher(date_string), mappings))
    # The same episode can appear on adjacent API dates; deduplicate safely.
    unique = {}
    for event in events:
        key = (event["channel_id"], event["start_utc"], event["title"])
        unique[key] = event
    return list(unique.values())
