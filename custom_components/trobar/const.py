# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the Trobar integration."""

DOMAIN = "trobar"

# How often the coordinators poll, in minutes: an option of the config
# entry (the options flow), 5 when unset.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL_MINUTES = 5
MIN_SCAN_INTERVAL_MINUTES = 1
MAX_SCAN_INTERVAL_MINUTES = 60

# Everything this integration registers is keyed by the config entry id,
# so two Trobar servers configured in the same Home Assistant instance
# never collide: Trobar device ids are per-server integers (device 1
# exists on both), and the entity unique ids are otherwise fixed strings
# ("server_reachable"). Before config entry minor version 2 only the
# server device was; __init__.async_migrate_entry moves the rest over.


# The hub-level "server" device's own identifier (trobar-ha#25).
def server_device_identifier(entry_id: str) -> tuple[str, str]:
    return (DOMAIN, entry_id)


# One Trobar device's identifier: its server-side id, within this entry.
def trobar_device_identifier(entry_id: str, device_id: int) -> tuple[str, str]:
    return (DOMAIN, f"{entry_id}_{device_id}")


# An entity's unique id: `key` within this entry.
def entity_unique_id(entry_id: str, key: str) -> str:
    return f"{entry_id}_{key}"
