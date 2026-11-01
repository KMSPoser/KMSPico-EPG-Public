#!/usr/bin/env python3
"""Publish original, operator-verified XMLTV event entries only.

No third-party guides are downloaded or republished here.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import parse_qsl, urlparse
import xml.etree.ElementTree as ET

from tvmaze_source import load_tvmaze_events


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Event times must be ISO 8601 UTC with a trailing Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("Event times must be UTC")
    return parsed


def xmltv_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def validated_events(config: dict, now: datetime) -> list[dict]:
    if config.get("version") != 1 or not isinstance(config.get("events"), list):
        raise ValueError("Unsupported event configuration")
    published = []
    seen = set()
    for event in config["events"]:
        required = ("channel_id", "channel_name", "title", "start_utc", "stop_utc", "verified_source_url")
        if not isinstance(event, dict) or any(not isinstance(event.get(k), str) or not event[k].strip() for k in required):
            raise ValueError("Every event must contain non-empty string fields")
        uri = urlparse(event["verified_source_url"])
        secret_keys = {"username", "password", "token", "access_token", "key", "api_key", "auth", "user", "pass", "sig"}
        if (uri.scheme != "https" or not uri.hostname or uri.username or uri.password
                or any(key.lower() in secret_keys for key, _ in parse_qsl(uri.query, keep_blank_values=True))
                or uri.path.lower().endswith((".m3u", ".m3u8", ".ts"))):
            raise ValueError("A public, credential-free HTTPS verification URL is required")
        if event.get("source", "operator") not in ("operator", "tvmaze"):
            raise ValueError("Unknown event provenance")
        if event.get("source") == "tvmaze" and uri.hostname != "www.tvmaze.com":
            raise ValueError("TVmaze events require a TVmaze episode source")
        start, stop = parse_utc(event["start_utc"]), parse_utc(event["stop_utc"])
        if stop <= start or stop - start > timedelta(hours=12):
            raise ValueError("Event duration must be positive and at most 12 hours")
        key = (event["channel_id"], start)
        if key in seen:
            raise ValueError("Duplicate event on channel at same start time")
        seen.add(key)
        if stop < now - timedelta(hours=6) or start > now + timedelta(days=14):
            continue
        published.append({**event, "start": start, "stop": stop})
    published.sort(key=lambda e: (e["channel_id"], e["start"]))
    last_stop = {}
    for event in published:
        channel = event["channel_id"]
        if channel in last_stop and event["start"] < last_stop[channel]:
            raise ValueError(f"Overlapping programme entries for {channel}")
        last_stop[channel] = event["stop"]
    return published


def make_guide(events: list[dict]) -> ET.Element:
    root = ET.Element("tv", {"generator-info-name": "KMSPico verified EPG supplement"})
    channels = {}
    for event in events:
        channel = channels.get(event["channel_id"])
        if channel is None:
            channel = ET.SubElement(root, "channel", {"id": event["channel_id"]})
            ET.SubElement(channel, "display-name").text = event["channel_name"]
            channels[event["channel_id"]] = channel
        elif channel.findtext("display-name") != event["channel_name"]:
            raise ValueError("Inconsistent display names for one channel ID")
    for event in events:
        programme = ET.SubElement(root, "programme", {
            "channel": event["channel_id"],
            "start": xmltv_time(event["start"]),
            "stop": xmltv_time(event["stop"]),
        })
        ET.SubElement(programme, "title", {"lang": "en"}).text = event["title"]
        description = ("Schedule data: TVmaze (CC BY-SA 4.0); broadcaster identity operator-confirmed"
                       if event.get("source") == "tvmaze" else "Operator-verified schedule entry")
        ET.SubElement(programme, "desc", {"lang": "en"}).text = description
    return root


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def build(config_path: Path, output_dir: Path, now: datetime, tvmaze_config: Path | None = None) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if tvmaze_config is not None:
        if config.get("version") != 1 or not isinstance(config.get("events"), list):
            raise ValueError("Unsupported event configuration")
        config["events"].extend(load_tvmaze_events(tvmaze_config, now))
    events = validated_events(config, now)
    root = make_guide(events)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    ET.fromstring(xml)  # Validate before replacing the published file.
    report = {
        "generated_utc": now.astimezone(timezone.utc).isoformat(),
        "kind": "verified-supplement-only",
        "channels": len({e["channel_id"] for e in events}),
        "programmes": len(events),
        "tvmaze_programmes": sum(e.get("source") == "tvmaze" for e in events),
        "note": "Not a replacement for the original online EPG",
    }
    atomic_write(output_dir / "guide.xml", xml)
    atomic_write(output_dir / "coverage.json", (json.dumps(report, indent=2) + "\n").encode("utf-8"))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/verified_events.json"))
    parser.add_argument("--out", type=Path, default=Path("docs"))
    parser.add_argument("--tvmaze-config", type=Path, default=Path("config/tvmaze_channels.json"))
    args = parser.parse_args()
    report = build(args.config, args.out, datetime.now(timezone.utc), args.tvmaze_config)
    print(f"Supplement EPG: {report['channels']} channels, {report['programmes']} programmes")


if __name__ == "__main__":
    main()
