# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the hub-level "server" device's scan button (trobar-ha#25,
trobar-server#474)."""

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.trobar.const import DOMAIN

from .test_sensor import SERVER_URL, _setup_entry

ACTIONS_SCAN_URL = "http://trobar.local/api/integrations/actions/scan"


def _button_entity_id(hass) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id("button", DOMAIN, "server_scan_library")


async def _press(hass, entity_id: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )


async def test_press_calls_the_actions_scan_endpoint(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(
        ACTIONS_SCAN_URL, status=202, json={"status": "started", "job_id": 1}
    )

    await _press(hass, _button_entity_id(hass))

    assert any(
        call[0].lower() == "post" and str(call[1]) == ACTIONS_SCAN_URL
        for call in aioclient_mock.mock_calls
    )


async def test_press_when_already_running_does_not_raise(hass, aioclient_mock):
    """A 409 ("already running") satisfies the same intent a press
    expresses -- it must not surface to the user as a failure."""
    await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(ACTIONS_SCAN_URL, status=409, json={"error": "already running"})

    await _press(hass, _button_entity_id(hass))  # must not raise


async def test_press_with_a_bad_token_raises_a_readable_error(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(ACTIONS_SCAN_URL, status=401)

    with pytest.raises(HomeAssistantError):
        await _press(hass, _button_entity_id(hass))


async def test_button_unavailable_when_the_server_cant_be_reached(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [])

    aioclient_mock.clear_requests()
    aioclient_mock.get(SERVER_URL, status=500)
    await entry.runtime_data.server.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_button_entity_id(hass))
    assert state.state == STATE_UNAVAILABLE
