# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Trobar integration: config entry setup.

trobar-ha#4 built the config flow and API client; trobar-ha#5 adds the
coordinator and forwards setup to the sensor platform. The config flow
already validated the URL and token once, at entry-creation time --
`async_config_entry_first_refresh` below is what re-checks reachability
on every Home Assistant restart, raising ConfigEntryNotReady (HA's
standard retry-with-backoff signal) if the server is unreachable or the
token was revoked since.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrobarApiClient
from .coordinator import TrobarDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type TrobarConfigEntry = ConfigEntry[TrobarDataUpdateCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Set up Trobar from a config entry."""
    client = TrobarApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    coordinator = TrobarDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Unload a Trobar config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
