# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Trobar integration: config entry setup.

trobar-ha#4 built the config flow and API client; trobar-ha#5 adds the
device coordinator and forwards setup to the sensor platform;
trobar-ha#25 adds the second, server-metrics coordinator and the
binary_sensor/button platforms for the hub-level "server" device;
trobar-ha#32 adds a third for playlist-mirror health, which unlike the
other two is allowed to be absent (see TrobarRuntimeData). The
config flow already validated the URL and token once, at entry-creation
time -- `async_config_entry_first_refresh` below is what re-checks
reachability on every Home Assistant restart, raising ConfigEntryNotReady
(HA's standard retry-with-backoff signal) if the server is unreachable,
or starting reauth (trobar-ha#28) if the token was revoked since.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrobarApiClient
from .coordinator import (
    TrobarDataUpdateCoordinator,
    TrobarMirrorsDataUpdateCoordinator,
    TrobarServerDataUpdateCoordinator,
)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


@dataclass
class TrobarRuntimeData:
    """One coordinator per independent failure domain -- see
    coordinator.py's module docstring for why they're separate rather
    than one fetch-everything coordinator.

    `mirrors` is None on a server older than 2.12.0, which is a supported
    configuration, not an error: the platforms skip those entities
    entirely rather than adding two that could only read unavailable.
    """

    devices: TrobarDataUpdateCoordinator
    server: TrobarServerDataUpdateCoordinator
    mirrors: TrobarMirrorsDataUpdateCoordinator | None


type TrobarConfigEntry = ConfigEntry[TrobarRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Set up Trobar from a config entry."""
    session = async_get_clientsession(hass)
    client = TrobarApiClient(session, entry.data[CONF_URL], entry.data[CONF_API_TOKEN])

    devices_coordinator = TrobarDataUpdateCoordinator(hass, entry, client)
    server_coordinator = TrobarServerDataUpdateCoordinator(hass, entry, client)
    # Sequential, not gathered: a ConfigEntryAuthFailed from either one
    # means the same admin-minted token is bad for both (trobar-server#474
    # unified the credential across all three /api/integrations/* routes),
    # so there's nothing to gain from racing them, and sequential keeps
    # whichever fails first the one HA reports.
    await devices_coordinator.async_config_entry_first_refresh()
    await server_coordinator.async_config_entry_first_refresh()

    # Mirrors (trobar-ha#32) is deliberately NOT a first_refresh: that
    # raises ConfigEntryNotReady on any failure, and this route's server
    # floor is 2.12.0 while the integration supports 2.8.0+. A 404 here
    # means "this server predates mirrors" -- refusing to set the entry
    # up at all over it would break every 2.9.0-2.11.x install that works
    # fine today. async_refresh() swallows the failure instead, and
    # `supported` distinguishes "route absent" from "poll failed": an
    # unreachable server keeps the entities (they read unavailable, which
    # is true), an old one never gets them. A bad token has already
    # raised ConfigEntryAuthFailed from one of the two refreshes above,
    # so nothing is being swallowed here that matters.
    mirrors_coordinator = TrobarMirrorsDataUpdateCoordinator(hass, entry, client)
    await mirrors_coordinator.async_refresh()
    if not mirrors_coordinator.supported:
        # Reports what was OBSERVED, not a diagnosis. This is the only
        # place in the integration where a 404 silently changes what gets
        # set up -- everywhere else it fails setup and the operator finds
        # out -- and _request_json maps *any* 404 to
        # TrobarServerTooOldError, so "old server" is a guess. A reverse
        # proxy whose path allowlist wasn't updated for the newer route
        # 404s exactly this one path and reads identically. Naming both
        # possibilities is the difference between a confident wrong
        # answer and a useful one when someone is grepping for why two
        # entities vanished.
        _LOGGER.info(
            "Trobar server at %s answered 404 for the mirrors route: either it "
            "predates 2.12.0, or that route isn't reachable (check any reverse "
            "proxy path rules). Skipping mirror health entities",
            entry.data[CONF_URL],
        )

    entry.runtime_data = TrobarRuntimeData(
        devices=devices_coordinator,
        server=server_coordinator,
        mirrors=mirrors_coordinator if mirrors_coordinator.supported else None,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Unload a Trobar config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
