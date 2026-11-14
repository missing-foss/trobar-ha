# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for device playlists (trobar-ha#19): the server's playlist totals,
each device's playlist count with its list in attributes, and the
"Sync playlists" button and action, from GET /api/integrations/playlists
and POST /api/integrations/actions/playlist-sync.

The payloads follow the route as the server builds it: exact counts, a
list capped at 100 per device with its truncation flag, and `available`
null for a playlist with no entries."""

import copy

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.trobar.const import DOMAIN

from .test_sensor import (
    DEVICES_URL,
    MIRRORS_URL,
    PHONE_DEVICE,
    PLAYLISTS_URL,
    SAMPLE_PLAYLISTS,
    WATCH_DEVICE,
    _setup_entry,
    _uid,
)

PLAYLIST_SYNC_URL = "http://trobar.local/api/integrations/actions/playlist-sync"

# A phone with more playlists than the list holds, one of them empty.
TRUNCATED_PLAYLISTS = {
    "playlists_total": 130,
    "playlists_with_gaps": 0,
    "devices": [
        {
            "device_id": 1,
            "name": "Test Phone",
            "playlists_count": 120,
            "playlists": [
                {
                    "playlist_id": i,
                    "title": f"Mix {i}",
                    "tracks": 0 if i == 0 else 10,
                    "matched": 0 if i == 0 else 10,
                    "available": None if i == 0 else 100,
                    "has_gaps": False,
                }
                for i in range(100)
            ],
            "playlists_truncated": True,
        }
    ],
}


def _entity_id(hass, platform: str, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, _uid(hass, key))


def _syncs(aioclient_mock) -> int:
    return sum(
        1
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "post" and str(call[1]) == PLAYLIST_SYNC_URL
    )


def _playlist_polls(aioclient_mock) -> int:
    return sum(
        1
        for call in aioclient_mock.mock_calls
        if call[0].lower() == "get" and str(call[1]) == PLAYLISTS_URL
    )


async def test_server_totals_are_read_verbatim(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    total = hass.states.get(_entity_id(hass, "sensor", "server_playlists_total"))
    assert total.state == "5"
    assert (
        hass.states.get(_entity_id(hass, "sensor", "server_playlists_with_gaps")).state
        == "1"
    )


async def test_each_device_reads_its_count_with_the_list_in_attributes(
    hass, aioclient_mock
):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])

    phone = hass.states.get(_entity_id(hass, "sensor", "1_playlists"))
    assert phone.state == "3"
    listed = phone.attributes["playlists"]
    assert [(p["title"], p["available"], p["has_gaps"]) for p in listed] == [
        ("Morning run", 100, False),
        ("Kitchen radio", 75, True),
        # Private: untitled, as the server sends it, with its availability.
        (None, 50, False),
    ]
    assert [p["private"] for p in listed] == [False, False, True]
    assert phone.attributes["playlists_truncated"] is False
    # An empty list is a real zero, not a missing device.
    watch = hass.states.get(_entity_id(hass, "sensor", "5_playlists"))
    assert watch.state == "0"
    assert watch.attributes["playlists"] == []


async def test_the_list_is_kept_out_of_the_recorder(hass, aioclient_mock):
    """100 playlists with their titles can pass the recorder's limit for
    attributes; the count and the truncation flag stay recorded."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    state = hass.states.get(_entity_id(hass, "sensor", "1_playlists"))
    unrecorded = state.state_info["unrecorded_attributes"]
    assert "playlists" in unrecorded
    assert "playlists_truncated" not in unrecorded


async def test_the_sensor_sits_on_the_trobar_device(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    registry = er.async_get(hass)
    playlists = registry.async_get(_entity_id(hass, "sensor", "1_playlists"))
    pending = registry.async_get(_entity_id(hass, "sensor", "1_pending_tracks"))
    assert playlists.device_id == pending.device_id


async def test_a_truncated_list_does_not_undercount(hass, aioclient_mock):
    await _setup_entry(
        hass, aioclient_mock, [PHONE_DEVICE], playlists=TRUNCATED_PLAYLISTS
    )

    state = hass.states.get(_entity_id(hass, "sensor", "1_playlists"))
    assert state.state == "120"
    assert len(state.attributes["playlists"]) == 100
    assert state.attributes["playlists_truncated"] is True
    # A playlist with no entries has no share, and that passes through.
    assert state.attributes["playlists"][0]["available"] is None


async def test_a_device_the_route_does_not_list_reads_unavailable(
    hass, aioclient_mock
):
    """Not zero: the route saying nothing about a device is no claim that
    it has no playlists."""
    payload = copy.deepcopy(SAMPLE_PLAYLISTS)
    payload["devices"] = [d for d in payload["devices"] if d["device_id"] != 1]
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE], playlists=payload)

    state = hass.states.get(_entity_id(hass, "sensor", "1_playlists"))
    assert state.state == STATE_UNAVAILABLE


async def test_a_removed_device_takes_its_playlists_sensor_with_it(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])
    assert _entity_id(hass, "sensor", "5_playlists") is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[PHONE_DEVICE])
    await entry.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert _entity_id(hass, "sensor", "5_playlists") is None
    assert _entity_id(hass, "sensor", "1_playlists") is not None


async def test_entities_are_skipped_on_a_server_without_the_route(
    hass, aioclient_mock
):
    entry = await _setup_entry(
        hass, aioclient_mock, [PHONE_DEVICE], playlists_status=404
    )

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.playlists is None
    for platform, key in (
        ("sensor", "server_playlists_total"),
        ("sensor", "server_playlists_with_gaps"),
        ("sensor", "1_playlists"),
        ("button", "server_sync_playlists"),
    ):
        assert _entity_id(hass, platform, key) is None, key
    # The device's other sensors are all there.
    assert _entity_id(hass, "sensor", "1_pending_tracks") is not None
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"playlists_route_missing_{entry.entry_id}"
    )


async def test_a_failed_poll_keeps_the_entities_but_unavailable(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    aioclient_mock.clear_requests()
    aioclient_mock.get(PLAYLISTS_URL, status=500)
    await entry.runtime_data.playlists.async_refresh()
    await hass.async_block_till_done()

    for platform, key in (
        ("sensor", "server_playlists_total"),
        ("sensor", "1_playlists"),
        ("button", "server_sync_playlists"),
    ):
        assert hass.states.get(_entity_id(hass, platform, key)).state == (
            STATE_UNAVAILABLE
        ), key
    assert entry.runtime_data.playlists.supported is True
    # Its own coordinator: the device's other sensors are untouched.
    assert hass.states.get(_entity_id(hass, "sensor", "1_pending_tracks")).state == "10"


async def test_a_failure_elsewhere_leaves_these_entities_alone(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    aioclient_mock.clear_requests()
    aioclient_mock.get(MIRRORS_URL, status=500)
    await entry.runtime_data.mirrors.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, "sensor", "1_playlists")).state == "3"
    assert hass.states.get(
        _entity_id(hass, "binary_sensor", "server_mirrors_problem")
    ).state == STATE_UNAVAILABLE


async def _press(hass) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": _entity_id(hass, "button", "server_sync_playlists")},
        blocking=True,
    )


async def test_press_starts_a_sync_and_polls_again(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    aioclient_mock.post(
        PLAYLIST_SYNC_URL, status=202, json={"status": "started", "job_id": 4}
    )
    polls_before = _playlist_polls(aioclient_mock)

    await _press(hass)
    await hass.async_block_till_done()

    assert _syncs(aioclient_mock) == 1
    assert _playlist_polls(aioclient_mock) == polls_before + 1


async def test_press_when_a_sync_is_running_does_not_raise(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    aioclient_mock.post(PLAYLIST_SYNC_URL, status=409, json={"error": "running"})

    await _press(hass)  # must not raise
    assert _syncs(aioclient_mock) == 1


async def test_press_with_a_bad_token_raises_a_readable_error(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    aioclient_mock.post(PLAYLIST_SYNC_URL, status=401)

    with pytest.raises(HomeAssistantError) as err:
        await _press(hass)
    assert err.value.translation_key == "token_rejected"


async def _sync(hass, entry_id: str):
    return await hass.services.async_call(
        DOMAIN,
        "sync_playlists",
        {"config_entry_id": entry_id},
        blocking=True,
        return_response=True,
    )


async def test_the_action_starts_a_sync_and_says_so(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    aioclient_mock.post(
        PLAYLIST_SYNC_URL, status=202, json={"status": "started", "job_id": 4}
    )
    polls_before = _playlist_polls(aioclient_mock)

    assert await _sync(hass, entry.entry_id) == {"started": True}
    await hass.async_block_till_done()
    assert _syncs(aioclient_mock) == 1
    assert _playlist_polls(aioclient_mock) == polls_before + 1


async def test_the_action_treats_a_running_sync_as_done(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    aioclient_mock.post(PLAYLIST_SYNC_URL, status=409, json={"error": "running"})

    assert await _sync(hass, entry.entry_id) == {"started": False}


async def test_the_action_refuses_a_server_without_the_route(hass, aioclient_mock):
    entry = await _setup_entry(
        hass, aioclient_mock, [PHONE_DEVICE], playlists_status=404
    )

    with pytest.raises(ServiceValidationError) as err:
        await _sync(hass, entry.entry_id)
    assert err.value.translation_key == "playlist_sync_not_supported"
    assert _syncs(aioclient_mock) == 0


async def test_the_action_refuses_an_unknown_entry(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    with pytest.raises(ServiceValidationError) as err:
        await _sync(hass, "not-an-entry")
    assert err.value.translation_key == "entry_not_loaded"
