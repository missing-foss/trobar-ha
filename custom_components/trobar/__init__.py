# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Trobar integration: config entry setup.

trobar-ha#4 built the config flow and API client; trobar-ha#5 adds the
device coordinator and forwards setup to the sensor platform;
trobar-ha#25 adds the second, server-metrics coordinator and the
binary_sensor/button platforms for the hub-level "server" device. The
config flow already validated the URL and token once, at entry-creation
time -- `async_config_entry_first_refresh` below is what re-checks
reachability on every Home Assistant restart, raising ConfigEntryNotReady
(HA's standard retry-with-backoff signal) if the server is unreachable,
or starting reauth (trobar-ha#28) if the token was revoked since.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, CONF_URL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TrobarApiClient
from .coordinator import TrobarDataUpdateCoordinator, TrobarServerDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]


@dataclass
class TrobarRuntimeData:
    """Both coordinators, one per independent failure domain -- see
    coordinator.py's module docstring for why they're separate rather
    than one fetch-everything coordinator."""

    devices: TrobarDataUpdateCoordinator
    server: TrobarServerDataUpdateCoordinator


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

    entry.runtime_data = TrobarRuntimeData(
        devices=devices_coordinator, server=server_coordinator
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Unload a Trobar config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
