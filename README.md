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
and replaces each of `docs/guide.xml` and `docs/coverage.json` atomically.

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

### Private catalog audit (v0.3)

`catalog_audit.py` helps diagnose the actual playlist without modifying it:

```bash
python3 catalog_audit.py --playlist /private/path/main.m3u --catalog /private/path/live_streams.json
```

It compares exact **stream IDs** to provider catalog entries, preserves Main's
`tvg-id` values, and flags rotating `NHL Event` slots. The tool retains no
stream URLs or passwords and never publishes its diagnostic results. Its
optional `--nhl-schedule /private/path/schedule.json --nhl-day YYYY-MM-DD`
argument can cross-check provider game labels against an NHL schedule snapshot.

A matching NHL game and time **does not prove the IPTV stream is carrying that
game**. All candidate entries remain `publishable_as_epg: false` until the
actual stream and programme can be verified separately. Never commit the
private input files or candidate output to this public repository.

### Safe pilot review and TVmaze discovery (v0.4)

The private audit also reports how many existing, real `tvg-id` values are
shared by multiple playlist channels. These may be intentional backups;
**do not change or deduplicate them**. A separate pilot queue suggests ten
potential US networks whose names, unique guide IDs, and provider catalog
guide IDs agree. This is a *review shortlist*, not proof of stream identity.

To check which pilot networks have episodes on TVmaze's free schedule:

```bash
python3 catalog_audit.py --playlist /private/path/main.m3u --catalog /private/path/live_streams.json --tvmaze-discovery-days 7
```

That opt-in lookup sends only calendar dates to TVmaze: no playlist, stream
IDs, names, accounts, or provider data are uploaded. Results are printed
locally, with `operator_verified: false` for all proposed mappings, and no
public EPG files are changed. Missing matches mean no usable episodes were
found in the sampled week, **not** that a network has no programmes.

Only after a person watches the actual TiviMate channel, confirms the
broadcaster, and checks the proposed network identity may they explicitly
approve that *specific* mapping in `config/tvmaze_channels.json`. Shared
guide IDs and sports event slots are excluded from this easy-start queue.

### Private mapping preflight (v0.5)

Before approving or publishing any TVmaze mapping, cross-check its exact
`tvg-id` against your *current* private Main playlist:

```bash
python3 catalog_audit.py --playlist /private/path/main.m3u --catalog /private/path/live_streams.json --tvmaze-mapping-preflight config/tvmaze_channels.json
```

The `tvmaze_mapping_preflight` portion of the local JSON report **blocks**
missing, shared, placeholder, or case-changed IDs. It **warns**, but does not
rewrite IDs, when channel display names or the provider's EPG ID disagree.
This check never opens a stream and cannot prove that it carries the claimed
broadcaster. A structurally consistent mapping is **not** an approval to
publish. The approved mapping must still be individually confirmed by a
person watching that channel in TiviMate. The Main playlist and Favorites
remain untouched.

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
