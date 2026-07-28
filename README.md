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

**Phase A — repo bring-up, no working integration yet.** This repo
currently ships a minimal `custom_components/trobar/` skeleton (manifest
only) so CI and Home Assistant's own validator (`hassfest`) have something
to check — no config flow, no entities, nothing you can actually add in
Home Assistant yet. See
[trobar-ha#1](https://github.com/missing-foss/trobar-ha/issues/1) for the
full bring-up checklist and phasing.

The integration itself depends on
[trobar-server#446](https://github.com/missing-foss/trobar-server/issues/446)
(a read-only API token for external integrations — **shipped in server
2.8.0**), since Home Assistant is a headless client that can't hold a
browser session the way Trobar's own web UI does.

## Requirements

- A running [Trobar server](https://github.com/missing-foss/trobar-server),
  version **2.8.0 or later** (for the read-only integration API).
- A Home Assistant instance to install this into, once there's something to
  install — see [Status](#status) above.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentation

Full Trobar documentation lives on the
[Trobar documentation site](https://missing-foss.github.io/trobar-server/).

## License

`GPL-3.0-or-later` — see [LICENSE](LICENSE). Contributions are welcome
under the same license; see [CONTRIBUTING.md](CONTRIBUTING.md).

Contributing a translation? See [Translating Trobar](https://missing-foss.github.io/trobar-server/project/translations/).
