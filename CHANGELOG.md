<!--
SPDX-FileCopyrightText: 2026 missing-foss

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

What changed for someone using the Trobar Home Assistant integration, by
version, in the
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) shape. A release's date
is its tag's. Versions before 0.3.0 are in the git log.

## [Unreleased]

## [0.5.0]

### Added

- Playlists: totals and playlists with gaps on the server device, and each
  device's playlists with how complete each one is.
- A "Sync playlists" button and a `trobar.sync_playlists` action.

Both need trobar-server 2.18.0 or later. With an older server, Settings →
Repairs says the playlist entities were skipped, the button isn't there, and
the action answers that the server needs a newer version. Everything else
works as in 0.4.0.

### Fixed

- "Mirrors failing" no longer records its `failing` and `coverage` lists in
  history. With both lists full they passed the recorder's 16 KiB limit for
  attributes, and the recorder then dropped every attribute of that state.
  The lists are still there to read live; the count and the per-target
  breakdown are still recorded.

## [0.4.0]

### Security

- Setup asks for the server's full URL, with `https://` or `http://`, instead of
  guessing `http://`: the token is sent to it on every update. A bare host now
  gets an error. Existing entries keep their URL.

### Added

- A `trobar.scan_library` action, with force.
- A poll interval per server.
- Repairs entries for a server route that answered 404.
- Diagnostics, with sensitive values redacted, and readable device models.
- Mirror coverage as sensor attributes.
- A leftover device can be removed by hand; a listed one can't.
- A "Playlist sources problem" binary sensor and a "Failing playlist sources"
  sensor, for playlist sources that keep failing to sync. They need a server
  newer than 2.17.0; an older one gets a Repairs notice and no entities.

### Changed

- Two Trobar servers can run side by side, and a 2.8.1 server sets up.
- Entities tell Home Assistant only when their value changes.
- The Occitan rosette replaces the bard in the brand images.
- The minimum Home Assistant version is 2026.3.1, the oldest release the
  tests run against; it was 2026.3.0.
- The install steps cover the Marketplace, which replaces HACS from Home
  Assistant 2026.11, with an "open in the Marketplace" link. The HACS steps
  stay for 2026.10 and older.

## [0.3.0]

### Added

- Mirror health as a sensor and a problem binary sensor.
- A reauth flow.
- A hub-level "server" device.
- A "sync completed" device trigger.
