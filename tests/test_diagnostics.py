# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The diagnostics download and the device registry entries (trobar-ha#21)."""

import copy

from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN
from custom_components.trobar.diagnostics import async_get_config_entry_diagnostics

from .test_mirrors import FAILING_MIRRORS
from .test_playlist_sources import ALERTING_SOURCES
from .test_sensor import (
    DEVICES_URL,
    MIRRORS_URL,
    PHONE_DEVICE,
    PLAYLIST_SOURCES_URL,
    SAMPLE_MIRRORS,
    SAMPLE_SERVER_STATUS,
    SERVER_URL,
    WATCH_DEVICE,
    _device_identifier,
    _registry_device,
    _setup_entry,
)


async def test_diagnostics_carry_no_names_or_addresses(hass, aioclient_mock):
    mirrors = copy.deepcopy(FAILING_MIRRORS)
    mirrors["short"] = [
        {"playlist_id": 21, "title": "Night Drive", "sink": "plex", "on_target": 9,
         "total": 10, "lacked": 1, "refused": 0, "run_at": "2026-07-30T09:00:00Z"}
    ]
    entry = await _setup_entry(
        hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE], mirrors=mirrors,
        playlist_sources=ALERTING_SOURCES,
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    text = repr(result)
    for secret in ("abc123", "trobar.local", "Test Phone", "Test Watch", "alice",
                   "bob", "Road Trip", "Focus", "Night Drive", "carol",
                   "Road trip mix"):
        assert secret not in text, secret
    data = result["entry"]
    assert data["data"][CONF_API_TOKEN] == data["data"][CONF_URL] == "**REDACTED**"
    assert data["unique_id"] == data["title"] == "**REDACTED**"
    phone = result["devices"]["data"][1]
    assert phone["name"] == phone["owner_username"] == "**REDACTED**"
    assert result["mirrors"]["data"]["failing"][0]["title"] == "**REDACTED**"
    assert result["mirrors"]["data"]["short"][0]["title"] == "**REDACTED**"
    sources = result["playlist_sources"]["data"]["alerting"]
    assert {s["account"] for s in sources} == {"**REDACTED**"}
    # What identifies no one stays: the kind, provider, runs and reason.
    assert [(s["provider"], s["runs"], s["reason"]) for s in sources] == [
        ("tidal", 371, "http_404"),
        ("jellyfin", 3, "not_found"),
        ("public", 4, "unavailable"),
    ]


async def test_diagnostics_keep_what_identifies_no_one(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["server"]["data"] == SAMPLE_SERVER_STATUS
    phone = result["devices"]["data"][1]
    assert phone["device_type"] == "phone"
    assert phone["max_size_bytes"] == 150000000000
    assert phone["sync_status"] == PHONE_DEVICE["sync_status"]
    assert result["mirrors"]["data"]["by_sink"] == SAMPLE_MIRRORS["by_sink"]
    assert result["mirrors"]["last_update_success"] is True


async def test_diagnostics_say_which_routes_this_server_lacks(hass, aioclient_mock):
    aioclient_mock.get(SERVER_URL, status=404)
    aioclient_mock.get(MIRRORS_URL, status=404)
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=404)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE], server_status=None)

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["server"] is None
    assert result["mirrors"] is None
    assert result["playlist_sources"] is None
    assert result["devices"]["data"][1]["device_type"] == "phone"


async def test_the_server_device_is_a_service_linking_to_the_web_ui(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [])
    server = _registry_device(hass, (DOMAIN, entry.entry_id))
    assert server.entry_type is dr.DeviceEntryType.SERVICE
    assert server.configuration_url == "http://trobar.local"
    assert server.sw_version == "2.9.0"


async def test_a_device_type_reads_as_trobar_names_it(hass, aioclient_mock):
    unknown = {**WATCH_DEVICE, "id": 9, "name": "Probe", "device_type": "car"}
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE, unknown])
    models = {
        device_id: _registry_device(hass, _device_identifier(hass, device_id)).model
        for device_id in (1, 5, 9)
    }
    # A type this integration doesn't know is shown as the server sends it.
    assert models == {1: "Phone", 5: "Smartwatch", 9: "car"}


async def test_a_restart_during_an_outage_keeps_the_known_server_version(
    hass, aioclient_mock
):
    """The server route answers 500 at startup, so its entities exist with
    no data; the mirrors entities write the same device. The version
    already on the device stays rather than being cleared."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        minor_version=2,
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "abc123"},
    )
    entry.add_to_hass(hass)
    registry = dr.async_get(hass)
    server = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Trobar Server",
        sw_version="2.9.0",
    )
    aioclient_mock.get(DEVICES_URL, json=[])
    aioclient_mock.get(SERVER_URL, status=500)
    aioclient_mock.get(MIRRORS_URL, json=copy.deepcopy(SAMPLE_MIRRORS))

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.runtime_data.server is not None  # the control: entities exist
    assert registry.async_get(server.id).sw_version == "2.9.0"
