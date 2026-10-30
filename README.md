# KMSPico supplemental EPG (public)

This is the public, credential-free companion to the private `KMSPico-EPG` project.
It publishes an XMLTV feed for **individually verified, permitted** programme
entries. It intentionally does **not** copy or redistribute the third-party
`epg41.xml.gz` guide, and it contains no IPTV credentials, stream URLs, or
private playlist catalog.

## Status

The guide is initially empty. It is a valid XMLTV document and a hosting test,
**not yet a replacement EPG**. Keep the original online EPG in TiviMate.

Future additions belong in `config/verified_events.json`. Each event must have
an independently verified HTTPS source URL and explicit UTC start/end times.
The builder checks the data, removes expired entries from the published output,
and writes `docs/guide.xml` plus `docs/coverage.json` atomically.

The scheduled GitHub Actions workflow runs every six hours and can also be
triggered manually. It republishes previously verified entries within their
valid time window; **the workflow does not automatically discover or verify
new broadcaster schedules**. Adding a legally reusable live listings source is
future work.

## Publish for free

1. Create a **public** GitHub repository with these files.
2. In **Settings → Pages**, select **Deploy from a branch**, then `main` and
   `/docs`. Save. Leave custom domains unset until the generated URL works.
3. Confirm the generated `https://<owner>.github.io/<repo>/guide.xml` endpoint.
4. Only add that URL as an *additional* EPG source after useful programme data
   has been verified. Do not replace the current EPG with this empty feed.

The repository is safe for public viewing: it contains only sample-free code,
the published empty guide, and a blank event configuration. Never commit M3U
playlists, Xtream credentials, API tokens, or URLs containing usernames or
passwords.

## Local checks

```bash
python3 -m unittest discover -s tests -q
python3 epg_public.py
```
