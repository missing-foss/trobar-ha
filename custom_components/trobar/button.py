# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Button platform for Trobar (trobar-ha#25, trobar-server#474).

Buttons on the hub-level "server" device: trigger a library rescan, and
(trobar-ha#19) sync playlists now.
This is the action trobar-server#474 was filed to decide whether an
integration credential should ever be allowed to cause -- the answer was
yes, scoped to exactly this.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrobarConfigEntry
from .api import TrobarApiError
from .const import entity_unique_id
from .coordinator import (
    TrobarPlaylistsDataUpdateCoordinator,
    TrobarServerDataUpdateCoordinator,
    translated_error,
)
from .device_info import server_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry: TrobarConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # None on a server older than 2.9.0 -- see TrobarRuntimeData.
    if entry.runtime_data.server is not None:
        async_add_entities([TrobarScanButton(entry.runtime_data.server)])
    # None on a server without the playlists route -- see TrobarRuntimeData.
    if entry.runtime_data.playlists is not None:
        async_add_entities([TrobarSyncPlaylistsButton(entry.runtime_data.playlists)])


class TrobarScanButton(
    CoordinatorEntity[TrobarServerDataUpdateCoordinator], ButtonEntity
):
    """Press to trigger a rescan. A CoordinatorEntity for its device
    linkage and normal availability (unavailable when the server can't
    be reached, same as TrobarScanRunningBinarySensor -- a button that
    will just 401/timeout isn't worth offering), even though it never
    reads coordinator.data for its own state; a button has none."""

    _attr_has_entity_name = True
    _attr_translation_key = "scan_library"

    def __init__(self, coordinator: TrobarServerDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_scan_library"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(
            self.coordinator.config_entry, (self.coordinator.data or {}).get("version")
        )

    async def async_press(self) -> None:
        """Trigger a rescan and request a refresh so `scan_running` (and,
        once it completes, `last_scan`) reflect it promptly rather than
        waiting for the next 5-minute poll. A 409 ("already running") is
        not an error -- async_trigger_scan() already absorbs it into a
        plain False return (trobar-server#478's own dedup already covers
        the abuse case a leaked/misfiring caller would create); the only
        thing left to raise here is a genuine TrobarApiError, which
        ButtonEntity surfaces to the user the same way any other action
        failure would be.
        """
        try:
            started = await self.coordinator.client.async_trigger_scan()
        except TrobarApiError as err:
            # Not ConfigEntryAuthFailed even for a 401 -- that signal is
            # only meaningful raised from a coordinator's own
            # _async_update_data (see update_coordinator.py); a button
            # press goes through HA's service-call path instead, which
            # doesn't watch for it. The next scheduled poll still catches
            # a bad token and starts reauth the normal way (trobar-ha#28)
            # within one interval; this just surfaces a readable error
            # for the press itself rather than a bare exception name.
            raise translated_error(err) from err
        if not started:
            _LOGGER.debug("Trobar scan already running; press had nothing new to start")
        await self.coordinator.async_request_refresh()


class TrobarSyncPlaylistsButton(
    CoordinatorEntity[TrobarPlaylistsDataUpdateCoordinator], ButtonEntity
):
    """Press to sync playlists now (trobar-ha#19), as the web UI's own
    button does. On the playlists coordinator, so it exists only where the
    server has the route and is unavailable when that poll fails. A 409
    (a sync already running or scheduled) is not an error, as for the
    scan button."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_playlists"

    def __init__(self, coordinator: TrobarPlaylistsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_sync_playlists"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    async def async_press(self) -> None:
        try:
            started = await self.coordinator.client.async_trigger_playlist_sync()
        except TrobarApiError as err:
            raise translated_error(err) from err
        if not started:
            _LOGGER.debug("Trobar playlist sync already running; nothing new to start")
        await self.coordinator.async_request_refresh()
