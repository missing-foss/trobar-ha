# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Diagnostics download (Settings -> Devices & Services -> Trobar -> ...):
the config entry and what each coordinator last fetched.

The file usually ends up attached to a public bug report, and with an
admin token it lists every user's devices, so it carries no names or
addresses: the token, the server's URL (also the entry's unique id and
title), device names, owners' usernames, playlist titles and the account
of each failing playlist source (a member's username or a link's title)
are redacted.
What helps debugging and identifies no one stays: versions, counts, sizes,
scan state, device types and sync status."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant

from . import TrobarConfigEntry

# Matched as keys at any depth: "title" is the entry's (its URL) and each
# failing or short mirror's playlist; "name" is a device's; "account" is
# an alerting playlist source's member or public link.
TO_REDACT = {
    CONF_API_TOKEN, CONF_URL, "unique_id", "title", "name", "owner_username", "account",
}


def _coordinator(coordinator) -> dict[str, Any] | None:
    if coordinator is None:
        return None  # this server has no such route (see TrobarRuntimeData)
    return {
        "last_update_success": coordinator.last_update_success,
        "data": coordinator.data,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TrobarConfigEntry
) -> dict[str, Any]:
    runtime = entry.runtime_data
    return async_redact_data({
        "entry": entry.as_dict(),
        "devices": _coordinator(runtime.devices),
        "server": _coordinator(runtime.server),
        "mirrors": _coordinator(runtime.mirrors),
        "playlist_sources": _coordinator(runtime.playlist_sources),
    }, TO_REDACT)
