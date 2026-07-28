# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sensor platform for Trobar (trobar-ha#5).

Five sensors per Trobar device, all reading from the shared coordinator's
last successful poll -- see trobar-ha#2 for the payload these are built
against and the null-handling notes that follow from it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrobarConfigEntry
from .api import parse_server_timestamp
from .const import DOMAIN
from .coordinator import TrobarDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TrobarSensorEntityDescription(SensorEntityDescription):
    """Extends SensorEntityDescription with how to read a device's value.

    `available_fn` is for the *permanent, by-design* nulls only -- e.g. a
    Garmin watch never reports storage, because the Garmin client never
    calls /api/device/storage (trobar-ha#2). Marking such a sensor
    unavailable says "this device structurally doesn't have this," which
    is honest; leaving native_value at None would instead show a bare
    "Unknown" that never resolves and looks like a bug. A transient null
    (e.g. last_synced_at before a device's first sync) is NOT this case:
    it's a real, meaningful value ("never"), so it stays available and
    simply reads as HA's normal empty state.
    """

    value_fn: Callable[[dict[str, Any]], Any]
    available_fn: Callable[[dict[str, Any]], bool] = lambda _device: True


SENSOR_DESCRIPTIONS: tuple[TrobarSensorEntityDescription, ...] = (
    TrobarSensorEntityDescription(
        key="pending_tracks",
        translation_key="pending_tracks",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device["sync_status"]["pending_count"],
    ),
    TrobarSensorEntityDescription(
        key="last_synced",
        translation_key="last_synced",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda device: parse_server_timestamp(
            device["sync_status"]["last_synced_at"]
        ),
    ),
    TrobarSensorEntityDescription(
        key="free_space",
        translation_key="free_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        value_fn=lambda device: device["reported_free_bytes"],
        available_fn=lambda device: device["reported_free_bytes"] is not None,
    ),
    TrobarSensorEntityDescription(
        key="total_space",
        translation_key="total_space",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        value_fn=lambda device: device["reported_total_bytes"],
        available_fn=lambda device: device["reported_total_bytes"] is not None,
    ),
    TrobarSensorEntityDescription(
        key="unknown_tracks",
        translation_key="unknown_tracks",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda device: device["unknown_track_count"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrobarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Trobar sensors for a config entry.

    Entities are added for whatever devices the coordinator already knows
    about, then kept in sync on every successful refresh: a device id
    that's newly present gets its sensors added, one that's newly absent
    has its HA device (and therefore its entities) removed outright.
    Removal, not "leave unavailable forever", because a device
    disappearing from the response isn't always transient -- a
    device-to-device transfer (trobar-server#442) *deletes* the old
    device server-side, permanently, so unavailable-forever would be a
    standing false report that something is merely offline.
    """
    coordinator = entry.runtime_data
    known_device_ids: set[int] = set()

    def _sync_devices() -> None:
        current_ids = set(coordinator.data)
        new_ids = current_ids - known_device_ids
        removed_ids = known_device_ids - current_ids

        if new_ids:
            async_add_entities(
                TrobarSensor(coordinator, device_id, description)
                for device_id in new_ids
                for description in SENSOR_DESCRIPTIONS
            )

        if removed_ids:
            device_registry = dr.async_get(hass)
            for device_id in removed_ids:
                device_entry = device_registry.async_get_device(
                    identifiers={(DOMAIN, str(device_id))}
                )
                if device_entry is not None:
                    device_registry.async_remove_device(device_entry.id)

        known_device_ids.clear()
        known_device_ids.update(current_ids)

    _sync_devices()
    entry.async_on_unload(coordinator.async_add_listener(_sync_devices))


class TrobarSensor(CoordinatorEntity[TrobarDataUpdateCoordinator], SensorEntity):
    """One sensor for one field of one Trobar device."""

    entity_description: TrobarSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrobarDataUpdateCoordinator,
        device_id: int,
        description: TrobarSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def _device(self) -> dict[str, Any] | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo | None:
        # A property, not a fixed _attr_, so a server-side rename is
        # picked up the next time HA reads it rather than frozen at
        # entity-creation time.
        device = self._device
        if device is None:
            return None
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            name=device["name"],
            manufacturer="Trobar",
            model=device["device_type"],
        )

    @property
    def available(self) -> bool:
        device = self._device
        if not self.coordinator.last_update_success or device is None:
            return False
        return self.entity_description.available_fn(device)

    @property
    def native_value(self) -> Any:
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        # #5's "worth deciding": a household's token sees every member's
        # devices (is_own: false for the others), same as the token
        # owner's own web UI. Surfacing both as attributes -- on every
        # sensor, not just one -- means any card or automation can filter
        # on "whose device is this" no matter which of a device's sensors
        # it happens to be built from.
        device = self._device
        if device is None:
            return None
        return {
            "is_own": device["is_own"],
            "owner_username": device["owner_username"],
        }
