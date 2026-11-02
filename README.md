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

### Compare free guides without changing Favorites (v0.6)

To decide whether an independently obtained XMLTV feed is a useful *secondary*
source, download its XMLTV `.xml` or `.xml.gz` file for **private inspection**,
then run:

```bash
python3 guide_compatibility.py --playlist /private/path/main.m3u --guide /private/path/candidate.xml.gz
```

This scans XMLTV channel declarations, comparing them against Main's existing
IDs. Its read-only JSON report separates **exact** ID matches from
**case-only candidates**, which must not be assumed to match in TiviMate.
It excludes placeholder event slots, counts repeated playlist entries, and
never prints a stream URL or republishes a source guide. The quick scan ends
at the first programme, assuming the usual XMLTV ordering of channel
declarations before programmes. It does not assess full schedule quality,
licensing, or whether a stream actually carries the alleged network.

An EPG file with many channels may still have almost no exact ID matches to
Main. Never rewrite Main's identifiers solely to satisfy an external guide:
doing so could disrupt existing EPG assignments and Favorites. Keep the
original EPG source and verify any new source and individual guide assignment
in TiviMate before deciding whether to use it.

### Check whether matching IDs actually have current programmes (v0.7 candidate)

The lightweight compatibility scan examines only channel declarations. To
determine whether the *potentially matching* channels have usable future
schedule data, run the optional, slower full-guide audit locally:

```bash
python3 guide_coverage.py --playlist /private/path/main.m3u --guide /private/path/candidate.xml.gz --hours 48
```

It counts upcoming programme intervals for exact ID matches and uniquely
case-only matching candidates, including the number with at least 24 hours of
coverage. It never prints programme titles or live stream URLs. Every case-only
match still requires individual manual EPG assignment and live broadcaster
verification; a full schedule does **not** prove a stream's identity.

Large XMLTV files can take time and memory to parse. An externally obtained
source's programmes are examined *privately*, not copied into this public
feed. The tool does not grant permission to redistribute them or make an EPG
source a safe replacement for the existing provider guide.

### Build a private Eagle-specific replacement inventory (v0.8 candidate)

The long-term objective is an independently maintained Eagle-compatible XMLTV
feed that can eventually replace the old `epg41.xml.gz` source. The first step
is to record **every** Main channel in an auditable private registry while
preserving its name, group, original `tvg-id`, and playlist position:

```bash
python3 eagle_registry.py --playlist /private/path/main.m3u \
  --baseline-guide /private/path/epg41.xml.gz \
  --output /private/path/Eagle_Channel_Registry.json
```

This compares guide **ID declarations only**; it does not copy third-party
programme listings. The saved JSON contains no stream URLs, stream IDs, or
credentials and must **never be committed** to the public repository. The
command refuses to write a registry inside this repository. It marks all
network identities as `unverified` and all source mappings as `not_assigned`.
Repeated real `tvg-id` values and placeholder event slots are flagged for
separate review, never renamed automatically.

Replacement cannot be declared ready merely because the candidate XMLTV has
matching IDs and fresh time slots. Each proposed network must be checked
against the actual live channel, and each programme source must authorize the
intended use. A staged pilot must validate real broadcast accuracy and guide
refreshes; TiviMate settings should be backed up beforehand. **Keep `epg41`
active until the independent Eagle guide passes those checks.**

### Measure real pilot schedule gaps (v0.9 candidate)

Even a correctly identified source network might have only a few scheduled
episodes in TVmaze. To quantify that limitation before anybody changes a
TiviMate guide assignment, run the private, read-only pilot audit:

```bash
python3 pilot_schedule_audit.py --playlist /private/path/main.m3u \
  --catalog /private/path/live_streams.json --window-hours 48
```

It fetches daily public TVmaze schedules, sending **only dates** to the API.
It screens the same ten low-ambiguity pilot channels, clips available episode
intervals to a 48-hour window, and reports percent of that window covered plus
the longest missing interval. Overlapping and repeated episodes are counted
only once. It never emits stream URLs, stream IDs, credentials, programme
titles, or a public guide, and it never changes or uploads Main. Keep the JSON
output private; it includes local channel IDs and is not a publication approval.

Every candidate's `actual_stream_verified` and `approved_for_public_guide`
remain false regardless of schedule coverage. A TVmaze schedule may identify
a network and some new episodes, but **it cannot certify an IPTV stream or fill
all repeats, movies, news, and sports**. For that reason, this source is useful
for a restricted supplement, not on its own a replacement for `epg41`.

### Compare multiple independently obtained guides (v1.0 candidate)

To identify which possible XMLTV sources deserve further research, compare
**local copies** of several guides against Main's unchanged `tvg-id` values:

```bash
python3 source_comparison.py --playlist /private/path/main.m3u \
  --candidate first=/private/path/first.xml.gz \
  --candidate second=/private/path/second.xml --hours 48 \
  > /private/path/source_comparison.json
```

This read-only comparison measures each declared channel's **exact** ID match,
future programme count, percentage of the selected window covered, and longest
missing interval. It separately flags case-only or ambiguous IDs, repeated
Main channel IDs, and malformed programme timestamps. A 95% coverage figure is
just a diagnostic threshold, **not** a publication or replacement approval.
The JSON output is **private**: it contains Main's existing channel IDs and
must not be committed to the public repository.

The audit never fetches or redistributes any source listings, stores programme
titles, changes a playlist, or assigns an EPG in TiviMate. Its source labels
contain no addresses or credentials. Identical channel IDs and full schedule
coverage are **not** proof of what the live Eagle stream actually shows.
For each candidate, independently check the actual stream identity and its
source's redistribution rights **before** proposing any public XMLTV entries.
All approvals remain false in this report, and `epg41` remains the active guide.

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
