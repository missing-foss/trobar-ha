# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Trobar integration: config entry setup (trobar-ha#4).

Coordinator and entities land in the follow-up (trobar-ha#5) -- this only
builds the API client and stores it on the entry, so a config entry is
fully functional (add / reload / remove) even before any platform exists.
The config flow already validated the URL and token once, at
entry-creation time; re-checking reachability on every Home Assistant
restart is the coordinator's job once it exists, not this function's.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrobarApiClient

type TrobarConfigEntry = ConfigEntry[TrobarApiClient]


async def async_setup_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Set up Trobar from a config entry."""
    entry.runtime_data = TrobarApiClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_API_TOKEN],
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Unload a Trobar config entry.

    Nothing to release yet -- no platforms are set up until trobar-ha#5,
    and the API client owns no resources of its own (it borrows Home
    Assistant's shared aiohttp session).
    """
    return True
