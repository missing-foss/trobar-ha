# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Device triggers for Trobar (trobar-ha#15).

One custom trigger: "sync_completed" -- pending tracks crossing below 1,
i.e. the device just finished catching up. Deliberately the *only* custom
trigger built here; #15's own "worth deciding" section asked which
candidates earn a device trigger versus being left to Home Assistant's
existing mechanisms, and the other three don't:

- **Storage low** needs no code at all. free_space/total_space already
  carry a state_class and a unit of measurement, which is exactly what
  Home Assistant's own generic sensor device trigger
  (homeassistant/components/sensor/device_trigger.py) requires to offer
  "value above/below X" automatically, for every sensor that qualifies.
  Building a second, Trobar-specific "storage low" trigger would just
  duplicate what's already three clicks away, and would force a decision
  #5 already flagged as unsettled (percent of what -- max_size_bytes or
  reported_total_bytes, given the cap can exceed free space) for no
  benefit over letting the user pick their own byte threshold directly.
- **Sync started / fell behind** is the mirror image of sync_completed
  (pending_tracks crossing above 0) and is exactly as well served by the
  same generic numeric trigger on that sensor -- not built here for the
  same reason.
- **The watchdog** ("hasn't synced in N days") fires on the *absence* of
  a change, which a state-transition trigger structurally cannot express.
  #15 itself suggested Home Assistant's own `template` trigger is the
  right tool; that's a documentation matter (a worked example, not a
  code path), not something to force into this file.

Unavailable sensors don't need special-casing here either: Home
Assistant's numeric_state condition already treats `unavailable`/
`unknown` as never satisfying above/below (see
homeassistant/helpers/condition.py), so a transition into or out of
unavailable can never masquerade as crossing the threshold. Confirmed by
reading that function directly rather than assumed.
"""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import (
    numeric_state as numeric_state_trigger,
)
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_ENTITY_ID,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

TRIGGER_TYPES = {"sync_completed"}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id_or_uuid,
        vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES),
    }
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """Offer "sync completed" for every Trobar device.

    Every Trobar device has exactly one pending_tracks sensor (trobar-ha#5),
    so this is always exactly zero or one trigger -- matched by unique_id
    suffix rather than by domain, since domain==DOMAIN alone would also
    match this device's other five sensors.
    """
    registry = er.async_get(hass)
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DEVICE_ID: device_id,
            CONF_DOMAIN: DOMAIN,
            CONF_ENTITY_ID: entry.id,
            CONF_TYPE: "sync_completed",
        }
        for entry in er.async_entries_for_device(registry, device_id)
        if entry.unique_id.endswith("_pending_tracks")
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Fire when pending_tracks crosses below 1.

    A fixed threshold, not exposed to the user: this is a semantic event
    ("this device just finished"), not a generic numeric comparison --
    that's what the sensor's own generic device trigger is for. A device
    that starts already at 0 (nothing to sync) never fires this, the same
    way it wouldn't read as a "completion" to someone watching it.
    """
    numeric_state_config = {
        numeric_state_trigger.CONF_PLATFORM: "numeric_state",
        numeric_state_trigger.CONF_ENTITY_ID: config[CONF_ENTITY_ID],
        numeric_state_trigger.CONF_BELOW: 1,
    }
    numeric_state_config = await numeric_state_trigger.async_validate_trigger_config(
        hass, numeric_state_config
    )
    return await numeric_state_trigger.async_attach_trigger(
        hass, numeric_state_config, action, trigger_info, platform_type="device"
    )


async def async_get_trigger_capabilities(
    hass: HomeAssistant, config: ConfigType
) -> dict[str, vol.Schema]:
    """No extra fields -- the threshold is fixed, not user-configurable."""
    return {"extra_fields": vol.Schema({})}
