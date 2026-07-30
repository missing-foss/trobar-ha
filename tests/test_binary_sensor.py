# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the hub-level "server" device's binary sensors (trobar-ha#25)."""

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.trobar.const import DOMAIN

from .test_sensor import SAMPLE_SERVER_STATUS, SERVER_URL, _setup_entry


def _entity_id(hass, platform: str, unique_id: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(platform, DOMAIN, unique_id)


async def test_reachable_is_on_after_a_successful_poll(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    state = hass.states.get(_entity_id(hass, "binary_sensor", "server_reachable"))
    assert state.state == STATE_ON


async def test_reachable_reads_off_not_unavailable_when_the_server_cant_be_reached(
    hass, aioclient_mock
):
    """trobar-ha#25, point 2: the whole reason this sensor exists is to
    answer "is the server reachable" -- it must still be able to answer
    "no" when a poll fails, not go unavailable and answer nothing."""
    entry = await _setup_entry(hass, aioclient_mock, [])
    assert (
        hass.states.get(_entity_id(hass, "binary_sensor", "server_reachable")).state
        == STATE_ON
    )

    aioclient_mock.clear_requests()
    aioclient_mock.get(SERVER_URL, status=500)
    await entry.runtime_data.server.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "binary_sensor", "server_reachable"))
    assert state.state == STATE_OFF
    assert state.state != STATE_UNAVAILABLE


async def test_scan_running_reflects_server_status(hass, aioclient_mock):
    running = {**SAMPLE_SERVER_STATUS, "scan_running": True}
    await _setup_entry(hass, aioclient_mock, [], server_status=running)

    state = hass.states.get(_entity_id(hass, "binary_sensor", "server_scan_running"))
    assert state.state == STATE_ON


async def test_scan_running_goes_unavailable_when_the_server_cant_be_reached(
    hass, aioclient_mock
):
    """Unlike "reachable" above, this one has normal availability -- if
    the server can't be reached, whether a scan is running genuinely is
    unknown, not "no"."""
    entry = await _setup_entry(hass, aioclient_mock, [])

    aioclient_mock.clear_requests()
    aioclient_mock.get(SERVER_URL, status=500)
    await entry.runtime_data.server.async_refresh()
    await hass.async_block_till_done()

    state = hass.states.get(_entity_id(hass, "binary_sensor", "server_scan_running"))
    assert state.state == STATE_UNAVAILABLE
