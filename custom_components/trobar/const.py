# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Constants for the Trobar integration."""

DOMAIN = "trobar"

# The hub-level "server" device's own identifier (trobar-ha#25) -- keyed
# by the config entry id, not a fixed literal like "server": per-device
# identifiers are (DOMAIN, str(trobar_device_id)), and a Trobar device id
# is always an integer, so a literal string can never collide with one.
# Using entry_id specifically (rather than the literal anyway) is what
# keeps two separate Trobar servers configured in the same Home Assistant
# instance from colliding on the same "server" device identifier.
def server_device_identifier(entry_id: str) -> tuple[str, str]:
    return (DOMAIN, entry_id)
