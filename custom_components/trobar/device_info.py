# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The two kinds of Home Assistant device this integration registers: the
hub-level "server" device, and one per Trobar device."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import (
    DeviceEntry,
    DeviceEntryType,
    DeviceInfo,
    DeviceRegistry,
)

from .const import server_device_identifier, trobar_device_identifier

# Trobar's own English names for its device types, the ones its web UI
# shows (an older "android" type reads as a phone there too). A type this
# list doesn't know is shown as the server sends it.
DEVICE_TYPE_MODELS = {
    "phone": "Phone",
    "android": "Phone",
    "tablet": "Tablet",
    "watch": "Smartwatch",
    "dap": "Dedicated audio player",
    "sdcard": "Removable storage",
    "folder": "Local folder",
}


def server_device_info(entry: ConfigEntry, version: str | None = None) -> DeviceInfo:
    """The server device: a service, not hardware, with a link to the
    Trobar web UI. `version` is only known to the server coordinator's
    entities; the others leave it out rather than clear it."""
    # The version goes in the constructor, never set afterwards: from core
    # 2026.11 a DeviceInfo is a dataclass, where item assignment is a
    # compatibility layer due to go, and keyword arguments work on both.
    version_kwarg = {"sw_version": version} if version is not None else {}
    return DeviceInfo(
        identifiers={server_device_identifier(entry.entry_id)},
        name="Trobar Server",
        manufacturer="Trobar",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=entry.data[CONF_URL],
        **version_kwarg,
    )


def trobar_device_info(entry: ConfigEntry, device: dict[str, Any]) -> DeviceInfo:
    """One Trobar device, under the server device."""
    device_type = device["device_type"]
    return DeviceInfo(
        identifiers={trobar_device_identifier(entry.entry_id, device["id"])},
        name=device["name"],
        manufacturer="Trobar",
        model=DEVICE_TYPE_MODELS.get(device_type, device_type),
    )


def find_entry_device(
    registry: DeviceRegistry, identifier: tuple[str, str], entry_id: str
) -> DeviceEntry | None:
    """The device this config entry registered under `identifier`.

    Newer cores look a device up per config entry, since identifiers are no
    longer unique across entries, and deprecate `async_get_device`. The
    floor core only has `async_get_device`; there this integration's
    identifiers are already entry-scoped, so it finds the same device."""
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry_id)
    return registry.async_get_device(identifiers={identifier})
