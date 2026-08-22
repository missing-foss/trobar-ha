# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Button platform for Trobar (trobar-ha#25, trobar-server#474).

One button on the hub-level "server" device: trigger a library rescan.
This is the action trobar-server#474 was filed to decide whether an
integration credential should ever be allowed to cause -- the answer was
yes, scoped to exactly this.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrobarConfigEntry
from .api import TrobarApiError
from .const import server_device_identifier
from .coordinator import _ERROR_MESSAGES, TrobarServerDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass, entry: TrobarConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TrobarScanButton(entry.runtime_data.server)])


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
    _attr_unique_id = "server_scan_library"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={server_device_identifier(self.coordinator.config_entry.entry_id)},
            name="Trobar Server",
            manufacturer="Trobar",
            sw_version=(self.coordinator.data or {}).get("version"),
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
            message = _ERROR_MESSAGES.get(type(err), str(err) or type(err).__name__)
            raise HomeAssistantError(message) from err
        if not started:
            _LOGGER.debug("Trobar scan already running; press had nothing new to start")
        await self.coordinator.async_request_refresh()
