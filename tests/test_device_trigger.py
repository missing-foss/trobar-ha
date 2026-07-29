# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Trobar "sync completed" device trigger (trobar-ha#15)."""

import copy

from homeassistant.components.device_automation import (
    DeviceAutomationType,
    async_get_device_automations,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.trobar.const import DOMAIN

from .test_sensor import DEVICES_URL, PHONE_DEVICE, _setup_entry


async def _sync_completed_trigger(hass, device_id: str) -> dict:
    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, [device_id]
    )
    return next(t for t in triggers[device_id] if t["type"] == "sync_completed")


async def test_sync_completed_trigger_is_offered(hass, aioclient_mock):
    """Every Trobar device offers exactly one "sync completed" trigger --
    not one per sensor, since domain-wide matching would offer six."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "1")})

    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, [device.id]
    )
    sync_completed = [t for t in triggers[device.id] if t["type"] == "sync_completed"]
    assert len(sync_completed) == 1


async def _setup_automation(hass, device_id: str, entity_id: str) -> None:
    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "trigger": {
                        "platform": "device",
                        "domain": DOMAIN,
                        "device_id": device_id,
                        "entity_id": entity_id,
                        "type": "sync_completed",
                    },
                    "action": {"service": "test.automation"},
                }
            ]
        },
    )
    await hass.async_block_till_done()


async def test_sync_completed_fires_when_pending_drops_to_zero(hass, aioclient_mock):
    """Fires on the transition from pending > 0 to pending == 0 -- the
    "just finished" moment, not merely "currently caught up"."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "1")})
    trigger = await _sync_completed_trigger(hass, device.id)

    calls = async_mock_service(hass, "test", "automation")
    await _setup_automation(hass, device.id, trigger["entity_id"])

    caught_up = copy.deepcopy(PHONE_DEVICE)
    caught_up["sync_status"]["pending_count"] = 0
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[caught_up])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(calls) == 1


async def test_sync_completed_does_not_fire_if_already_zero_at_setup(
    hass, aioclient_mock
):
    """A device that starts (or stays) at zero pending tracks never "just
    finished" -- there's no transition into zero to fire on."""
    already_caught_up = copy.deepcopy(PHONE_DEVICE)
    already_caught_up["sync_status"]["pending_count"] = 0
    entry = await _setup_entry(hass, aioclient_mock, [already_caught_up])
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "1")})
    trigger = await _sync_completed_trigger(hass, device.id)

    calls = async_mock_service(hass, "test", "automation")
    await _setup_automation(hass, device.id, trigger["entity_id"])

    # A refresh that reports the same (already zero) value again -- nothing
    # transitioned, so nothing should fire.
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[already_caught_up])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(calls) == 0


async def test_sync_completed_does_not_fire_while_still_pending(hass, aioclient_mock):
    """A drop in pending count that doesn't reach zero isn't "completed"."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "1")})
    trigger = await _sync_completed_trigger(hass, device.id)

    calls = async_mock_service(hass, "test", "automation")
    await _setup_automation(hass, device.id, trigger["entity_id"])

    still_going = copy.deepcopy(PHONE_DEVICE)
    still_going["sync_status"]["pending_count"] = 1
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[still_going])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert len(calls) == 0
