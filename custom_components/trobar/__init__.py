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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TrobarApiClient
from .const import (
    DOMAIN,
    entity_unique_id,
    server_device_identifier,
    trobar_device_identifier,
)
from .coordinator import (
    TrobarDataUpdateCoordinator,
    TrobarMirrorsDataUpdateCoordinator,
    TrobarPlaylistsDataUpdateCoordinator,
    TrobarPlaylistSourcesDataUpdateCoordinator,
    TrobarServerDataUpdateCoordinator,
)
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

_LOGGER = logging.getLogger(__name__)


@dataclass
class TrobarRuntimeData:
    """One coordinator per independent failure domain -- see
    coordinator.py's module docstring for why they're separate rather
    than one fetch-everything coordinator.

    `mirrors` is None on a server older than 2.12.0, `server` on one
    older than 2.9.0, `playlist_sources` on one without playlist-source
    health (2.17.0 and older), and `playlists` on one without playlist
    entities. All are supported configurations, not errors: the
    platforms skip those entities entirely rather than adding ones that
    could only read unavailable.
    """

    devices: TrobarDataUpdateCoordinator
    server: TrobarServerDataUpdateCoordinator | None
    mirrors: TrobarMirrorsDataUpdateCoordinator | None
    playlist_sources: TrobarPlaylistSourcesDataUpdateCoordinator | None
    playlists: TrobarPlaylistsDataUpdateCoordinator | None = None


type TrobarConfigEntry = ConfigEntry[TrobarRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions (services.py), once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Set up Trobar from a config entry."""
    session = async_get_clientsession(hass)
    client = TrobarApiClient(session, entry.data[CONF_URL], entry.data[CONF_API_TOKEN])

    devices_coordinator = TrobarDataUpdateCoordinator(hass, entry, client)
    # The device list is the one route every supported server has, so it
    # alone is the first_refresh: it is what checks reachability, and the
    # token (one admin-minted credential for every /api/integrations/*
    # route, trobar-server#474), on every restart.
    await devices_coordinator.async_config_entry_first_refresh()

    # The server route arrived in 2.9.0, and 2.8.1 is a supported floor
    # for the per-device sensors (README), so the server coordinator is
    # optional exactly as mirrors is below: a first_refresh would turn its
    # 404 into ConfigEntryNotReady and retry the entry forever.
    server_coordinator = TrobarServerDataUpdateCoordinator(hass, entry, client)
    await server_coordinator.async_refresh()
    if not server_coordinator.supported:
        _LOGGER.info(
            "Trobar server at %s answered 404 for the server route: either it "
            "predates 2.9.0, or that route isn't reachable (check any reverse "
            "proxy path rules). Skipping the server device's entities",
            entry.data[CONF_URL],
        )
    _report_route(hass, entry, "server", "2.9.0", server_coordinator.supported)

    # Mirrors (trobar-ha#32) is deliberately NOT a first_refresh: that
    # raises ConfigEntryNotReady on any failure, and this route's server
    # floor is 2.12.0 while the integration supports 2.8.0+. A 404 here
    # means "this server predates mirrors" -- refusing to set the entry
    # up at all over it would break every 2.9.0-2.11.x install that works
    # fine today. async_refresh() swallows the failure instead, and
    # `supported` distinguishes "route absent" from "poll failed": an
    # unreachable server keeps the entities (they read unavailable, which
    # is true), an old one never gets them. A bad token has already
    # raised ConfigEntryAuthFailed from the device refresh above,
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
    _report_route(hass, entry, "mirrors", "2.12.0", mirrors_coordinator.supported)

    # Playlist-source health: optional the same way, for the same reasons.
    # No version in its notice yet: the first server release with it isn't
    # tagged.
    sources_coordinator = TrobarPlaylistSourcesDataUpdateCoordinator(
        hass, entry, client
    )
    await sources_coordinator.async_refresh()
    if not sources_coordinator.supported:
        _LOGGER.info(
            "Trobar server at %s answered 404 for the playlist sources route: "
            "either it predates playlist-source health, or that route isn't "
            "reachable (check any reverse proxy path rules). Skipping "
            "playlist-source health entities",
            entry.data[CONF_URL],
        )
    _report_route(hass, entry, "playlist_sources", None, sources_coordinator.supported)

    # Each device's playlists, and the playlist-sync action: optional the
    # same way. No version in its notice yet, as for playlist sources.
    playlists_coordinator = TrobarPlaylistsDataUpdateCoordinator(hass, entry, client)
    await playlists_coordinator.async_refresh()
    if not playlists_coordinator.supported:
        _LOGGER.info(
            "Trobar server at %s answered 404 for the playlists route: either "
            "it predates playlist entities, or that route isn't reachable "
            "(check any reverse proxy path rules). Skipping playlist entities "
            "and the playlist-sync button",
            entry.data[CONF_URL],
        )
    _report_route(hass, entry, "playlists", None, playlists_coordinator.supported)

    entry.runtime_data = TrobarRuntimeData(
        devices=devices_coordinator,
        server=server_coordinator if server_coordinator.supported else None,
        mirrors=mirrors_coordinator if mirrors_coordinator.supported else None,
        playlist_sources=sources_coordinator if sources_coordinator.supported else None,
        playlists=playlists_coordinator if playlists_coordinator.supported else None,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The options flow's poll interval reaches the coordinators by reload.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: TrobarConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """1.1 -> 1.2: scope every entity unique id and every Trobar device's
    identifier by this entry's id (const.py says why). Updated in place,
    so entity ids, history, device ids and the automations that name them
    all carry over; only the registry keys change.

    A Trobar device registered under 1.1 by two entries at once (both
    servers had a device with that id, so they shared one HA device) is
    left alone: it can't be given to either. Each entry registers its own
    under the new identifier on setup."""
    if entry.version > 1:
        return False  # a downgrade from a future major version
    if entry.minor_version < 2:
        prefix = f"{entry.entry_id}_"

        @callback
        def _scoped(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
            if entity_entry.unique_id.startswith(prefix):
                return None
            return {
                "new_unique_id": entity_unique_id(
                    entry.entry_id, entity_entry.unique_id
                )
            }

        await er.async_migrate_entries(hass, entry.entry_id, _scoped)

        device_registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            if device.config_entries != {entry.entry_id}:
                continue
            identifiers = {
                trobar_device_identifier(entry.entry_id, int(value))
                if domain == DOMAIN and value.isdigit()
                else (domain, value)
                for domain, value in device.identifiers
            }
            if identifiers != device.identifiers:
                device_registry.async_update_device(
                    device.id, new_identifiers=identifiers
                )

        hass.config_entries.async_update_entry(entry, minor_version=2)
    return True


# The optional routes whose 404 skips entities (TrobarRuntimeData).
_OPTIONAL_ROUTES = ("server", "mirrors", "playlist_sources", "playlists")


def _route_issue_id(entry: TrobarConfigEntry, route: str) -> str:
    return f"{route}_route_missing_{entry.entry_id}"


def _report_route(
    hass: HomeAssistant,
    entry: TrobarConfigEntry,
    route: str,
    version: str | None,
    supported: bool,
) -> None:
    """A Repairs entry for an optional route that answered 404, so the
    entities it would have brought aren't missing in silence; removed at
    the first setup that finds the route. A warning, not an error, and not
    fixable from Home Assistant: an older server is a supported setup, and
    the fix (upgrade, or a reverse proxy that forwards the path) is on the
    server side. The text names both causes, as the log line does. With no
    `version`, the text names none: for a route whose first release isn't
    known yet."""
    issue_id = _route_issue_id(entry, route)
    if supported:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=f"{route}_route_missing",
        translation_placeholders={"url": entry.data[CONF_URL]}
        | ({"version": version} if version is not None else {}),
    )


async def async_remove_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> None:
    """A removed server takes its Repairs entries with it."""
    for route in _OPTIONAL_ROUTES:
        ir.async_delete_issue(hass, DOMAIN, _route_issue_id(entry, route))


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: TrobarConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device by hand only when the server no longer
    lists it, so a leftover can be cleaned up and a live device can't be.

    A device absent from a successful poll is already removed on its own
    (sensor.py), because the device route returns the full list; this
    covers whatever that misses. The server device is never removable:
    it belongs to the config entry, not to the device list."""
    if server_device_identifier(entry.entry_id) in device_entry.identifiers:
        return False
    current = {
        trobar_device_identifier(entry.entry_id, device_id)
        for device_id in entry.runtime_data.devices.data
    }
    return not current & device_entry.identifiers


async def async_unload_entry(hass: HomeAssistant, entry: TrobarConfigEntry) -> bool:
    """Unload a Trobar config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
