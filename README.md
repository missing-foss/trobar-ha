<!--
SPDX-FileCopyrightText: 2026 missing-foss

SPDX-License-Identifier: GPL-3.0-or-later
-->

# trobar-ha

[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/missing-foss/trobar-ha/badge)](https://securityscorecards.dev/viewer/?uri=github.com/missing-foss/trobar-ha)

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
forcing that model would fight what the integration is actually for. See
[trobar-server#270](https://github.com/missing-foss/trobar-server/issues/270)
for the full design RFC and why.

## Status

**Working, installable, not yet in the HACS default store.** The
integration adds via config flow (URL + an admin-minted integration
token, validated live; re-authenticates in place if the token is later
revoked). It polls `GET /api/integrations/devices` and creates one Home
Assistant device per Trobar device with six sensors each: pending
tracks, last synced, free space, total space, unknown tracks, and owner
(diagnostic).

It also creates one hub-level **"server" device**: reachability and
scan-running binary sensors, version/track-count/library-size/last-scan
sensors, and a **"Scan library" button** that triggers a rescan
(trobar-server#474). Reachability is always available, even when the
server can't be reached at all — that's the one state it exists to
report.

Ships in English and French.

A **"finished syncing" device trigger** is buildable from the automation
UI ("When… Trobar device finished syncing"), no template needed.
"Storage low" and "sync started" don't need a dedicated trigger — Home
Assistant's own generic sensor trigger already offers "value above/below"
on the storage and pending-tracks sensors. A "hasn't synced in N days"
watchdog isn't a state transition, so it's better built with Home
Assistant's own `template` trigger than modelled here.

Not yet done: notifications and a default-store HACS listing — that's
Phase B of [trobar-ha#1](https://github.com/missing-foss/trobar-ha/issues/1),
deferred until the integration has seen some real use.

The integration depends on
[trobar-server#446](https://github.com/missing-foss/trobar-server/issues/446)
/ [#474](https://github.com/missing-foss/trobar-server/issues/474) /
[#475](https://github.com/missing-foss/trobar-server/issues/475) (an
integration token for external tools, admin-minted, covering both reads
and the rescan action), since Home Assistant is a headless client that
can't hold a browser session the way Trobar's own web UI does.

## Installation

Not in the HACS default store yet — add it as a **custom repository**:

1. HACS → ⋮ → **Custom repositories**
2. URL `https://github.com/missing-foss/trobar-ha`, category **Integration**
3. Install, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Trobar**, and enter
   your server's URL and a token from **Profile → Integrations** in
   Trobar's web UI — that tab is admin-only, since minting a token
   requires it

## Requirements

- A running [Trobar server](https://github.com/missing-foss/trobar-server),
  version **2.9.0 or later** for the full feature set (the server device,
  reachability, and the rescan button all need
  [trobar-server#474](https://github.com/missing-foss/trobar-server/issues/474)/
  [#475](https://github.com/missing-foss/trobar-server/issues/475)).
  **2.8.1** is the floor if you only want the per-device sensors (2.8.0
  shipped the read-only integration API; 2.8.1 fixed a
  boolean-serialization bug in it — see
  [trobar-server#449](https://github.com/missing-foss/trobar-server/issues/449)) —
  but note that on 2.8.1, tokens were still mintable by any logged-in
  user, and upgrading to 2.9.0 later revokes any token that wasn't
  created by an admin (see trobar-server's own
  [upgrade notes](https://missing-foss.github.io/trobar-server/operations/upgrading/)).
- Home Assistant **2026.3.0 or later** (for locally-shipped brand images —
  see `hacs.json`).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

Full Trobar documentation lives on the
[Trobar documentation site](https://missing-foss.github.io/trobar-server/).

## License

`GPL-3.0-or-later` — see [LICENSE](LICENSE). Contributions are welcome
under the same license; see [CONTRIBUTING.md](CONTRIBUTING.md).

Contributing a translation? See [Translating Trobar](https://missing-foss.github.io/trobar-server/project/translations/).
