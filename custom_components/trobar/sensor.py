# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Sensor platform for Trobar (trobar-ha#5, server sensors,
mirror health in #32).

Six sensors per Trobar device, all reading from the shared coordinator's
last successful poll. The null handling here follows from the shape of a
real payload. Four more sensors
live on the hub-level "server" device (trobar-ha#25), reading from the
separate server coordinator, plus a fifth for mirror health (trobar-ha#32)
on its own coordinator again -- see coordinator.py's module docstring for
why that's three coordinators, not one.
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
from homeassistant.const import EntityCategory, UnitOfInformation
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TrobarConfigEntry
from .api import parse_server_timestamp
from .const import entity_unique_id, trobar_device_identifier
from .coordinator import (
    TrobarDataUpdateCoordinator,
    TrobarMirrorsDataUpdateCoordinator,
    TrobarPlaylistsDataUpdateCoordinator,
    TrobarPlaylistSourcesDataUpdateCoordinator,
    TrobarServerDataUpdateCoordinator,
)
from .device_info import find_entry_device, server_device_info, trobar_device_info

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
    TrobarSensorEntityDescription(
        # #17: Option C as decided -- a diagnostic sensor, not a device-name
        # change (Option A, declined) or a suggested_area (Option B,
        # declined). owner_username is never null: devices.owner_user_id is
        # NOT NULL server-side and the endpoint inner-joins on it, so an
        # ownerless device would be absent from the response entirely
        # rather than present with a null owner -- no available_fn needed.
        # Reads through the coordinator like every other sensor here, so a
        # trobar-server#442 transfer (which changes ownership at runtime)
        # is picked up on the next refresh rather than frozen at setup.
        key="owner",
        translation_key="owner",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda device: device["owner_username"],
    ),
)


@dataclass(frozen=True, kw_only=True)
class TrobarServerSensorEntityDescription(SensorEntityDescription):
    """Server-metrics counterpart of TrobarSensorEntityDescription above --
    no available_fn, since none of #475's fields have a permanent-null
    case the way a Garmin watch's storage does; a missing/failed poll is
    already handled by CoordinatorEntity's own availability, not per-field."""

    value_fn: Callable[[dict[str, Any]], Any]


SERVER_SENSOR_DESCRIPTIONS: tuple[TrobarServerSensorEntityDescription, ...] = (
    TrobarServerSensorEntityDescription(
        key="version",
        translation_key="server_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data["version"],
    ),
    TrobarServerSensorEntityDescription(
        key="tracks",
        translation_key="server_tracks",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["track_count"],
    ),
    TrobarServerSensorEntityDescription(
        key="library_size",
        translation_key="server_library_size",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        suggested_display_precision=1,
        value_fn=lambda data: data["total_bytes"],
    ),
    TrobarServerSensorEntityDescription(
        key="last_scan",
        translation_key="server_last_scan",
        device_class=SensorDeviceClass.TIMESTAMP,
        # #475's own null semantics (trobar-server docs): null means "no
        # completed scan to report on right now" -- while a scan is
        # running, not "unknown". A real, meaningful null, so this stays
        # available and reads as HA's normal empty timestamp state,
        # same reasoning as sync_status.last_synced_at above.
        value_fn=lambda data: parse_server_timestamp(data["last_scan_at"]),
    ),
)


class TrobarMirrorsFailingSensor(
    CoordinatorEntity[TrobarMirrorsDataUpdateCoordinator], SensorEntity
):
    """Instance-wide count of currently-failing playlist x sink mirror
    pairs (trobar-ha#32, trobar-server#506).

    State is `mirrors_failing` verbatim, so the common automation is a
    bare `> 0` with no templating. Two things it deliberately does NOT
    do:

    - it does not count `failing[]`. That array is capped at 50 entries;
      `mirrors_failing` and `by_sink` are exact. Counting the array would
      under-report on exactly the installs that most need the alert,
      since one dead target can fail every playlist pointed at it, which
      is precisely when the cap bites.
    - it does not translate `error_code`. Those are deliberately
      language-independent machine codes (trobar-server#428) and they
      travel in an attribute, which Home Assistant does not localise --
      a translation here would have no surface to render on. They are
      passed through raw for templates to map. See the PR for why this is
      deferred rather than done.

    The worklist, per-sink breakdown and truncation flag all go in
    attributes rather than the state: HA caps state at 255 characters,
    which a 50-entry list would blow through immediately.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "server_mirrors_failing"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The two worklists are for cards and templates, not history: full, at
    # 50 entries each with their titles, they pass the recorder's 16 KiB
    # limit for attributes, which then drops them all with a warning. The
    # state and the counts beside them are still recorded.
    _unrecorded_attributes = frozenset({"failing", "coverage"})

    def __init__(self, coordinator: TrobarMirrorsDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_mirrors_failing"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["mirrors_failing"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        data = self.coordinator.data
        attrs = {
            "by_sink": data["by_sink"],
            "failing": data["failing"],
            "failing_truncated": data["failing_truncated"],
        }
        # Coverage: playlist x sink pairs whose last write left tracks off
        # the target. Not an alarm: a partial copy is the normal state of a
        # target with a different library, so it stays out of the state and
        # out of the problem binary sensor. A server from before coverage
        # sends none of these keys, and its attributes stay as they were.
        if "mirrors_short" in data:
            attrs["mirrors_short"] = data["mirrors_short"]
            attrs["coverage"] = data.get("short", [])
            attrs["coverage_truncated"] = data.get("short_truncated", False)
        return attrs


class TrobarPlaylistSourcesFailingSensor(
    CoordinatorEntity[TrobarPlaylistSourcesDataUpdateCoordinator], SensorEntity
):
    """How many playlist sources keep failing, by the server's alert rule
    (3 failed runs in a row, spanning at least 12 hours).

    State is `sources_alerting` verbatim, never a count of `alerting`,
    which is capped. The worklist goes in attributes with its truncation
    flag, as the mirrors sensor's does, and so does `sources_failing`:
    sources that failed their last run(s) but don't alert yet, for anyone
    who wants an earlier warning. Each entry's `reason` is the server's
    raw code, passed through as mirrors' `error_code` is.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "server_playlist_sources_failing"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: TrobarPlaylistSourcesDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, "server_playlist_sources_failing"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["sources_alerting"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None:
            return None
        data = self.coordinator.data
        return {
            "alerting": data["alerting"],
            "alerting_truncated": data["alerting_truncated"],
            "sources_failing": data["sources_failing"],
            "sources_total": data["sources_total"],
        }


PLAYLISTS_SERVER_SENSOR_DESCRIPTIONS: tuple[
    TrobarServerSensorEntityDescription, ...
] = (
    TrobarServerSensorEntityDescription(
        key="playlists_total",
        translation_key="server_playlists_total",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["playlists_total"],
    ),
    TrobarServerSensorEntityDescription(
        key="playlists_with_gaps",
        translation_key="server_playlists_with_gaps",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data["playlists_with_gaps"],
    ),
)


class TrobarPlaylistsServerSensor(
    CoordinatorEntity[TrobarPlaylistsDataUpdateCoordinator], SensorEntity
):
    """A server-wide playlist count (trobar-ha#19), on the server device but
    read from the playlists coordinator, so a server without the route
    simply has neither sensor."""

    entity_description: TrobarServerSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrobarPlaylistsDataUpdateCoordinator,
        description: TrobarServerSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, f"server_{description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(self.coordinator.config_entry)

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


class TrobarDevicePlaylistsSensor(
    CoordinatorEntity[TrobarPlaylistsDataUpdateCoordinator], SensorEntity
):
    """How many playlists one device has (trobar-ha#19), with each
    playlist's completeness in attributes.

    Which devices get one is decided by the devices coordinator, as for
    every other per-device sensor, so a device removed there loses this
    sensor with the rest of its entities. The value comes from the
    playlists coordinator; a device that coordinator does not list (yet)
    reads unavailable rather than zero, since zero would be a claim.

    State is `playlists_count`, never a count of `playlists`, which the
    server caps at 100. The list goes in attributes as the server sends
    it, with its truncation flag, and is kept out of the recorder.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "playlists"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # The list is for cards and templates, not history: at up to 100
    # entries with their titles it can pass the recorder's 16 KiB limit
    # for attributes, which then drops them all with a warning. The count
    # (the state) and the truncation flag are still recorded.
    _unrecorded_attributes = frozenset({"playlists"})

    def __init__(
        self,
        coordinator: TrobarPlaylistsDataUpdateCoordinator,
        devices: TrobarDataUpdateCoordinator,
        device_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._devices = devices
        self._device_id = device_id
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, f"{device_id}_playlists"
        )

    @property
    def _entry(self) -> dict[str, Any] | None:
        data = self.coordinator.data
        if data is None:
            return None
        for device in data["devices"]:
            if device["device_id"] == self._device_id:
                return device
        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        device = (self._devices.data or {}).get(self._device_id)
        if device is None:
            return None
        return trobar_device_info(self.coordinator.config_entry, device)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self._entry is not None

    @property
    def native_value(self) -> int | None:
        entry = self._entry
        if entry is None:
            return None
        return entry["playlists_count"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        entry = self._entry
        if entry is None:
            return None
        return {
            "playlists": entry["playlists"],
            "playlists_truncated": entry["playlists_truncated"],
        }


class TrobarServerSensor(
    CoordinatorEntity[TrobarServerDataUpdateCoordinator], SensorEntity
):
    """One sensor for one field of the hub-level server device."""

    entity_description: TrobarServerSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TrobarServerDataUpdateCoordinator,
        description: TrobarServerSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, f"server_{description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        return server_device_info(
            self.coordinator.config_entry, (self.coordinator.data or {}).get("version")
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TrobarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Trobar sensors for a config entry.

    Per-device entities are added for whatever devices the coordinator
    already knows about, then kept in sync on every successful refresh: a
    device id that's newly present gets its sensors added, one that's
    newly absent has its HA device (and therefore its entities) removed
    outright. Removal, not "leave unavailable forever", because a device
    disappearing from the response isn't always transient -- a
    device-to-device transfer (trobar-server#442) *deletes* the old
    device server-side, permanently, so unavailable-forever would be a
    standing false report that something is merely offline.

    The four server sensors (trobar-ha#25) are simpler: exactly one
    "server" device exists for the lifetime of the config entry, so
    they're added once, with no add/remove tracking -- or not at all on a
    server too old to have the server route.
    """
    # None on a server older than 2.9.0 -- see TrobarRuntimeData.
    server = entry.runtime_data.server
    if server is not None:
        async_add_entities(
            TrobarServerSensor(server, description)
            for description in SERVER_SENSOR_DESCRIPTIONS
        )

    # None on a server older than 2.12.0 -- see TrobarRuntimeData. Adding
    # nothing is the point: an entity that can only ever read unavailable
    # is worse than an absent one, because it looks like a fault.
    if entry.runtime_data.mirrors is not None:
        async_add_entities([TrobarMirrorsFailingSensor(entry.runtime_data.mirrors)])

    # None on a server without playlist-source health -- see TrobarRuntimeData.
    if entry.runtime_data.playlist_sources is not None:
        async_add_entities(
            [TrobarPlaylistSourcesFailingSensor(entry.runtime_data.playlist_sources)]
        )

    # None on a server without the playlists route -- see TrobarRuntimeData.
    playlists = entry.runtime_data.playlists
    if playlists is not None:
        async_add_entities(
            TrobarPlaylistsServerSensor(playlists, description)
            for description in PLAYLISTS_SERVER_SENSOR_DESCRIPTIONS
        )

    coordinator = entry.runtime_data.devices
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
            if playlists is not None:
                async_add_entities(
                    TrobarDevicePlaylistsSensor(playlists, coordinator, device_id)
                    for device_id in new_ids
                )

        if removed_ids:
            device_registry = dr.async_get(hass)
            for device_id in removed_ids:
                device_entry = find_entry_device(
                    device_registry,
                    trobar_device_identifier(entry.entry_id, device_id),
                    entry.entry_id,
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
        self._attr_unique_id = entity_unique_id(
            coordinator.config_entry.entry_id, f"{device_id}_{description.key}"
        )

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
        return trobar_device_info(self.coordinator.config_entry, device)

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
