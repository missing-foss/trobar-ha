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
integration adds via config flow (URL + read-only token, validated live),
then polls `GET /api/integrations/devices` and creates one Home Assistant
device per Trobar device with five sensors each: pending tracks, last
synced, free space, total space, unknown tracks. Ships in English and
French.

Not yet done: device triggers, notifications, and a default-store HACS
listing — that's Phase B of
[trobar-ha#1](https://github.com/missing-foss/trobar-ha/issues/1), deferred
until the integration has seen some real use.

The integration depends on
[trobar-server#446](https://github.com/missing-foss/trobar-server/issues/446)
(a read-only API token for external integrations), since Home Assistant is
a headless client that can't hold a browser session the way Trobar's own
web UI does.

## Installation

Not in the HACS default store yet — add it as a **custom repository**:

1. HACS → ⋮ → **Custom repositories**
2. URL `https://github.com/missing-foss/trobar-ha`, category **Integration**
3. Install, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Trobar**, and enter
   your server's URL and a token from **Profile → Integrations** in
   Trobar's web UI

## Requirements

- A running [Trobar server](https://github.com/missing-foss/trobar-server),
  version **2.8.1 or later** (2.8.0 shipped the read-only integration API;
  2.8.1 fixed a boolean-serialization bug in it — see
  [trobar-server#449](https://github.com/missing-foss/trobar-server/issues/449)).
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
