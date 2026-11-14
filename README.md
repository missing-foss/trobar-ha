<!--
SPDX-FileCopyrightText: 2026 missing-foss

SPDX-License-Identifier: GPL-3.0-or-later
-->

# trobar-ha

[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/missing-foss/trobar-ha/badge)](https://securityscorecards.dev/viewer/?uri=github.com/missing-foss/trobar-ha)
[![Support on Ko-fi](https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/missingfoss)

Home Assistant integration for [Trobar](https://github.com/missing-foss/trobar-server)
— the household dashboard for offline music sync: per-device status, card
space, and automations on sync events.

## What this is (and isn't)

Trobar doesn't play or stream music — it syncs files onto offline devices
(a phone, an SD card, a Garmin watch). This integration surfaces that
**sync lifecycle**, not playback: last-synced time, tracks pending,
storage used/free, provider health, auto-fit fill — the trustworthy
cross-device dashboard Trobar's own clients don't have a single place for
— plus notifications and automations on sync events ("DAP finished
syncing", ">90% full", "hasn't synced in N days").

**Deliberately not a `media_player`.** Trobar isn't a renderer, and
forcing that model would fight what the integration is actually for: it
surfaces the sync lifecycle, not playback.

## Status

**Working, installable, not yet in the Marketplace's default catalog.** The
integration adds via config flow (URL + an admin-minted integration
token, validated live; re-authenticates in place if the token is later
revoked). It polls `GET /api/integrations/devices` and creates one Home
Assistant device per Trobar device with six sensors each: pending
tracks, last synced, free space, total space, unknown tracks, and owner
(diagnostic). It polls every 5 minutes by default; the integration's
**Configure** button sets the interval, from 1 to 60 minutes, per server.

It also creates one hub-level **"server" device**: reachability and
scan-running binary sensors, version/track-count/library-size/last-scan
sensors, and a **"Scan library" button** that triggers a rescan. The
same rescan is the **`trobar.scan_library`** action for automations and
scripts, with a `force` option to re-read every file, not only the ones
changed since the last scan; it answers whether it started a scan (it
doesn't when one is already running).
Reachability is always available, even when the server can't be reached at
all — that's the one state it exists to report.

Two more entities on the server device watch the places playlist syncs read
from (the library source, members' own listings, linked streaming accounts and
public links): **"Playlist sources problem"**, on while any of them keeps
failing, and **"Failing playlist sources"**, how many, with the list as
attributes. Both follow the server's rule — 3 failed syncs in a row, over at
least 12 hours — so one bad night doesn't page anyone.

Playlists have their own: **"Playlists"** and **"Playlists with gaps"** on
the server device (gaps being entries not found in the library that nobody
has excluded or accepted), and a **"Playlists"** sensor on each Trobar
device, how many it has, with each one's title and how much of it is in the
library as attributes (a device lists at most 100; the count is always
exact). A private playlist is listed with its availability but no title,
and `private: true`: the server never sends its name. A **"Sync playlists"** button, and the **`trobar.sync_playlists`**
action, sync them now instead of at the server's next scheduled sync; the
action answers whether it started one.

Ships in English and French.

A **"finished syncing" device trigger** is buildable from the automation
UI ("When… Trobar device finished syncing"), no template needed.
"Storage low" and "sync started" don't need a dedicated trigger — Home
Assistant's own generic sensor trigger already offers "value above/below"
on the storage and pending-tracks sensors. A "hasn't synced in N days"
watchdog isn't a state transition, so it's better built with Home
Assistant's own `template` trigger than modelled here.

Not yet done: notifications and a listing in the Marketplace's default catalog — deferred
until the integration has seen some real use.

The integration depends on Trobar's integration API and an admin-minted
integration token, which covers both the reads and the two actions.
Home Assistant is a headless client and can't hold a browser session the
way Trobar's own web UI does, which is why a token is needed at all.

## Installation

Trobar isn't in the Marketplace's default catalog yet, so it's added as a
custom repository.

**Home Assistant 2026.11 and later** (the Marketplace, under **Settings**):

[![Open your Home Assistant instance and open this repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=missing-foss&repository=trobar-ha&category=integration)

The link opens the repository in your Marketplace, which offers to add it
as a custom repository first. Download it, then restart Home Assistant.

**Home Assistant 2026.10 and older** (HACS, installed separately):

1. HACS → ⋮ → **Custom repositories**
2. URL `https://github.com/missing-foss/trobar-ha`, category **Integration**
3. Download, then restart Home Assistant

**Then, either way:** **Settings → Devices & Services → Add Integration → Trobar**, and enter
   your server's full URL, with `https://` or `http://`, and a token from **Profile → Integrations** in
   Trobar's web UI — that tab is admin-only, since minting a token
   requires it

## Requirements

- A running [Trobar server](https://github.com/missing-foss/trobar-server),
  version **2.12.0 or later** for the full feature set: the mirror-health
  entities need 2.12.0, and the server device, reachability and the rescan
  button need **2.9.0**. The playlist-source and playlist entities need
  **2.18.0**. On an older server, **Settings → Repairs** says
  which of them were skipped and why.
  **2.8.1** is the floor if you only want the per-device sensors (2.8.0
  shipped the read-only integration API; 2.8.1 fixed a
  boolean-serialization bug in it) —
  but note that on 2.8.1, tokens were still mintable by any logged-in
  user, and upgrading to 2.9.0 later revokes any token that wasn't
  created by an admin (see trobar-server's own
  [upgrade notes](https://missing-foss.github.io/trobar-server/operations/upgrading/)).
- Home Assistant **2026.3.1 or later** (for locally-shipped brand images —
 see `hacs.json`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

Full Trobar documentation lives on the
[Trobar documentation site](https://missing-foss.github.io/trobar-server/).

## Support

The integration is free software, like the rest of Trobar. If it's useful in your Home Assistant, you can [support Trobar on Ko-fi](https://ko-fi.com/missingfoss).

Support pays for test devices, infrastructure and Claude. Mostly, it buys a good coffee and keeps the motivation going for the next projects.

## License

`GPL-3.0-or-later` — see [LICENSE](LICENSE). Contributions are welcome
under the same license; see [CONTRIBUTING.md](CONTRIBUTING.md).

Contributing a translation? See [Translating Trobar](https://missing-foss.github.io/trobar-server/project/translations/).
