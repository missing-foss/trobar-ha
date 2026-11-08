# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Binary sensor platform for Trobar (trobar-ha#25, mirror health).

Four binary sensors on the hub-level "server" device: reachability,
whether a library scan is currently running, whether any playlist
mirror is failing, and whether any playlist source keeps failing. The
first two read from the server coordinator, not the device one; the
others from the mirrors and playlist-sources coordinators -- see
coordinator.py's module docstring for why they are kept separate.
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrobarConfigEntry
from .const import entity_unique_id
from .coordinator import (
    TrobarMirrorsDataUpdateCoordinator,
    TrobarPlaylistSourcesDataUpdateCoordinator,
    TrobarServerDataUpdateCoordinator,
)
from .device_info import server_device_info


async def async_setup_entry(
    hass, entry: TrobarConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    # None on a server older than 2.9.0 -- see TrobarRuntimeData.
    coordinator = entry.runtime_data.server
    if coordinator is not None:
        async_add_entities(
            [
                TrobarReachableBinarySensor(coordinator),
                TrobarScanRunningBinarySensor(coordinator),
            ]
        )

    # None on a server older than 2.12.0 -- see TrobarRuntimeData.
    if entry.runtime_data.mirrors is not None:
        async_add_entities(
            [TrobarMirrorsProblemBinarySensor(entry.runtime_data.mirrors)]
        )

    # None on a server without playlist-source health -- see TrobarRuntimeData.
    if entry.runtime_data.playlist_sources is not None:
        async_add_entities(
            [
                TrobarPlaylistSourcesProblemBinarySensor(
                    entry.runtime_data.playlist_sources
                )
            ]
        )


class _TrobarServerBinarySensorBase(
    CoordinatorEntity[TrobarServerDataUpdateCoordinator], BinarySensorEntity
):
    _attr_has_entity_name = True
    _unique_key: str

    def __init__(self, coordinator: TrobarServerDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, self._unique_key
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(
            self.coordinator.config_entry, (self.coordinator.data or {}).get("version")
        )


class TrobarReachableBinarySensor(_TrobarServerBinarySensorBase):
    """trobar-ha#25, point 2: this is the one entity in the whole
    integration that must NOT go unavailable when the server can't be
    reached -- that's precisely the case it exists to report. It never
    calls CoordinatorEntity's own `available` (which is
    `coordinator.last_update_success`); it reads that value directly as
    its STATE instead. The obvious implementation (marking every entity
    unavailable on a failed poll, then reading this one's state normally)
    would make the connectivity sensor go unavailable exactly when it
    should read `off` -- useless for the one automation ("alert if
    unreachable") it exists for.
    """

    _attr_translation_key = "reachable"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _unique_key = "server_reachable"

    @property
    def available(self) -> bool:
        # CoordinatorEntity.available is a @property returning
        # coordinator.last_update_success -- a plain _attr_available
        # class attribute would be shadowed by it and silently do
        # nothing, so this has to override the property itself.
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class TrobarScanRunningBinarySensor(_TrobarServerBinarySensorBase):
    """Whether a library scan is queued or actively running right now
    (trobar-server#475's scan_running). Normal availability here -- if
    the server can't be reached at all, "is a scan running" genuinely is
    unknown, unlike TrobarReachableBinarySensor above."""

    _attr_translation_key = "scan_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _unique_key = "server_scan_running"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["scan_running"]


class TrobarMirrorsProblemBinarySensor(
    CoordinatorEntity[TrobarMirrorsDataUpdateCoordinator], BinarySensorEntity
):
    """Whether any playlist mirror is currently failing (trobar-ha#32).

    The idiomatic HA shape for "something needs attention": a `problem`
    device class reads as Detected/OK in the UI and needs no numeric
    comparison in an automation, unlike the count sensor it sits beside.
    Both exist because they answer different questions -- "is anything
    broken" versus "how much".

    Reads `mirrors_failing`, never `len(failing)`: that array is capped
    at 50 (trobar-server#506), and while a cap can't hide a non-zero
    count from a boolean, deriving it from the list would still be wrong
    the moment the payload's own exact counter and its truncated worklist
    disagree. Use the number that is documented as exact.

    Normal availability: if the server can't be reached, whether mirrors
    are failing genuinely is unknown -- the same reasoning as
    TrobarScanRunningBinarySensor above, not TrobarReachableBinarySensor.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "mirrors_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: TrobarMirrorsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_mirrors_problem"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["mirrors_failing"] > 0


class TrobarPlaylistSourcesProblemBinarySensor(
    CoordinatorEntity[TrobarPlaylistSourcesDataUpdateCoordinator], BinarySensorEntity
):
    """Whether any playlist source keeps failing: on while
    `sources_alerting` is above zero.

    It follows the server's alert rule (3 failed runs in a row, spanning
    at least 12 hours), so an automation on it doesn't page over one bad
    night. It reads the count, never `len(alerting)`, since that list is
    capped -- the rule TrobarMirrorsProblemBinarySensor follows. Normal
    availability, for the same reason as that one.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "playlist_sources_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: TrobarPlaylistSourcesDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_playlist_sources_problem"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["sources_alerting"] > 0
