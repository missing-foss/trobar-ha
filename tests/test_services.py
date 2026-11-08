# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The trobar.scan_library action (trobar-ha#21)."""

import copy

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN

from .test_button import ACTIONS_SCAN_URL
from .test_sensor import (
    DEVICES_URL,
    MIRRORS_URL,
    PHONE_DEVICE,
    PLAYLIST_SOURCES_URL,
    SERVER_URL,
    _setup_entry,
)


def _scan_bodies(aioclient_mock) -> list:
    return [
        call[2]
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == ACTIONS_SCAN_URL
    ]


def _server_polls(aioclient_mock) -> int:
    return sum(
        1
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and str(call[1]) == SERVER_URL
    )


async def _scan(hass, entry_id: str, **data):
    return await hass.services.async_call(
        DOMAIN,
        "scan_library",
        {"config_entry_id": entry_id, **data},
        blocking=True,
        return_response=True,
    )


async def test_force_reaches_the_server_and_the_answer_says_it_started(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(
        ACTIONS_SCAN_URL, status=202, json={"status": "started", "job_id": 1}
    )
    polls_before = _server_polls(aioclient_mock)

    response = await _scan(hass, entry.entry_id, force=True)
    await hass.async_block_till_done()

    assert response == {"started": True}
    assert _scan_bodies(aioclient_mock) == [{"force": True}]
    # The server is asked again at once, so "scan running" reflects it.
    assert _server_polls(aioclient_mock) == polls_before + 1


async def test_force_defaults_to_off_and_a_running_scan_is_not_an_error(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(ACTIONS_SCAN_URL, status=409, json={"error": "running"})

    response = await _scan(hass, entry.entry_id)

    assert response == {"started": False}
    assert _scan_bodies(aioclient_mock) == [{"force": False}]


async def test_a_bad_token_is_a_readable_error(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(ACTIONS_SCAN_URL, status=401)

    with pytest.raises(HomeAssistantError, match="rejected the token") as err:
        await _scan(hass, entry.entry_id)
    assert err.value.translation_key == "token_rejected"


@pytest.mark.parametrize(
    ("status", "key", "text"),
    [
        (404, "server_too_old", "too old for the integration API"),
        (429, "rate_limited", "rate-limiting this token"),
    ],
)
async def test_a_failed_scan_is_a_translated_error(
    hass, aioclient_mock, status, key, text
):
    entry = await _setup_entry(hass, aioclient_mock, [])
    aioclient_mock.post(ACTIONS_SCAN_URL, status=status)

    with pytest.raises(HomeAssistantError, match=text) as err:
        await _scan(hass, entry.entry_id)
    assert err.value.translation_domain == "trobar"
    assert err.value.translation_key == key


async def test_an_unknown_entry_is_refused_before_any_request(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, "not-an-entry")
    assert err.value.translation_key == "entry_not_loaded"
    assert _scan_bodies(aioclient_mock) == []


async def test_a_loaded_entry_of_another_integration_is_refused(hass, aioclient_mock):
    """The selector only offers trobar entries, but an automation or a
    script can name any entry id."""
    await _setup_entry(hass, aioclient_mock, [])
    other = MockConfigEntry(domain="other", state=ConfigEntryState.LOADED)
    other.add_to_hass(hass)
    assert other.state is ConfigEntryState.LOADED  # the control

    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, other.entry_id)
    assert err.value.translation_key == "entry_not_loaded"
    assert _scan_bodies(aioclient_mock) == []


async def test_an_unloaded_entry_is_refused(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [])
    assert await hass.config_entries.async_unload(entry.entry_id)

    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, entry.entry_id)
    assert err.value.translation_key == "entry_not_loaded"


async def test_a_server_without_the_scan_action_is_refused(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=404)
    aioclient_mock.get(MIRRORS_URL, status=404)
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=404)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert entry.runtime_data.server is None  # the control: a 2.8.1 server

    with pytest.raises(ServiceValidationError) as err:
        await _scan(hass, entry.entry_id)
    assert err.value.translation_key == "scan_not_supported"
    assert _scan_bodies(aioclient_mock) == []
