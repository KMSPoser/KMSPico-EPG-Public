# KMSPico supplemental EPG (public)

This is the public, credential-free companion to the private `KMSPico-EPG` project.
It publishes an XMLTV feed for **individually verified, permitted** programme
entries. It intentionally does **not** copy or redistribute the third-party
`epg41.xml.gz` guide, and it contains no IPTV credentials, stream URLs, or
private playlist catalog.

## Status

The guide remains empty until channel-to-network identities are individually
confirmed. It is a valid XMLTV document and a hosting test,
**not yet a replacement EPG**. Keep the original online EPG in TiviMate.

Future additions belong in `config/verified_events.json`. Each event must have
an independently verified HTTPS source URL and explicit UTC start/end times.
The builder checks the data, removes expired entries from the published output,
and writes `docs/guide.xml` plus `docs/coverage.json` atomically.

The scheduled GitHub Actions workflow runs every six hours and can also be
triggered manually. It republishes previously verified entries within their
valid time window.

### Optional free TVmaze auto-updating listings

The generator supports the [TVmaze free schedule API](https://www.tvmaze.com/api),
which offers episode schedules under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
with attribution and share-alike conditions. The published guide credits TVmaze
in each imported programme description. TVmaze schedules are *episode-based*;
they do **not** verify IPTV stream contents, accurately cover every local
station, or reliably show all live sporting events.

To activate a channel, edit `config/tvmaze_channels.json` with a mapping of the
exact current XMLTV `tvg-id`/channel ID and display name from TiviMate to the
corresponding TVmaze network ID and name. Set `operator_verified: true` **only
after watching that actual stream and confirming the network identity**. The
configuration deliberately starts with no channel mappings. Example *schema
only* (not a recommendation to map any particular stream):

```json
{
  "version": 1,
  "channels": [{
    "channel_id": "example.us",
    "channel_name": "Example Channel",
    "tvmaze_network_id": 40,
    "tvmaze_network_name": "CNN",
    "kind": "network",
    "operator_verified": true
  }]
}
```

After a mapping is approved, each six-hour refresh queries the US daily TVmaze
schedules for the current week. Failed requests halt publication, preserving
the last good guide. A changed network name is excluded rather than guessed.
No playlist or stream URL is read or modified by this automation.

### Preserve TiviMate Favorites

1. Back up TiviMate settings/data on the Fire Stick before adding any guide.
2. Keep **all original M3U links, `tvg-id` values, playlists, and Favorites**.
3. Add the supplemental `guide.xml` only as a **secondary EPG source** after
   it has verified real programmes. Manually assign guide IDs for a few
   channels as a pilot, without removing the original EPG source.
4. If a programme is wrong, remove just its guide assignment or supplemental
   source. Do not delete/re-add the existing playlist.

The missing Devils/Vegas game remains **unresolved**: the fact that an IPTV
stream played that game on a channel named CW 8 Missoula does not establish
its future broadcast schedule or channel identity.

## Publish for free

1. Create a **public** GitHub repository with these files.
2. In **Settings → Pages**, select **Deploy from a branch**, then `main` and
   `/docs`. Save. Leave custom domains unset until the generated URL works.
3. Confirm the generated `https://<owner>.github.io/<repo>/guide.xml` endpoint.
4. Only add that URL as an *additional* EPG source after useful programme data
   has been verified. Do not replace the current EPG with this empty feed.

The repository is safe for public viewing: it contains code,
the published initially empty guide, and blank event/mapping configurations. Never commit M3U
playlists, Xtream credentials, API tokens, or URLs containing usernames or
passwords.

## Local checks

```bash
python3 -m unittest discover -s tests -q
python3 epg_public.py
```
