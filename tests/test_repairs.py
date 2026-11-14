# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Repairs entries for a route that answered 404 (trobar-ha#21)."""

import copy

from homeassistant.helpers import issue_registry as ir

from custom_components.trobar.const import DOMAIN

from .test_sensor import (
    DEVICES_URL,
    MIRRORS_URL,
    PHONE_DEVICE,
    PLAYLIST_SOURCES_URL,
    PLAYLISTS_URL,
    SAMPLE_MIRRORS,
    SAMPLE_SERVER_STATUS,
    SERVER_URL,
    _setup_entry,
)


def _issue(hass, route: str, entry):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"{route}_route_missing_{entry.entry_id}"
    )


async def test_a_server_with_every_route_has_no_repairs(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _issue(hass, "server", entry) is None
    assert _issue(hass, "mirrors", entry) is None
    assert _issue(hass, "playlist_sources", entry) is None


async def test_each_missing_route_is_a_warning_naming_its_version(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=404)
    aioclient_mock.get(MIRRORS_URL, status=404)
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=404)
    aioclient_mock.get(PLAYLISTS_URL, status=404)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    server, mirrors = _issue(hass, "server", entry), _issue(hass, "mirrors", entry)
    assert server.severity is ir.IssueSeverity.WARNING
    assert server.is_fixable is False
    assert (server.translation_key, server.translation_placeholders) == (
        "server_route_missing",
        {"url": "http://trobar.local", "version": "2.9.0"},
    )
    assert (mirrors.translation_key, mirrors.translation_placeholders["version"]) == (
        "mirrors_route_missing",
        "2.12.0",
    )
    # No first release to name yet: the notice says "predates" and no version.
    sources = _issue(hass, "playlist_sources", entry)
    assert sources.severity is ir.IssueSeverity.WARNING
    assert (sources.translation_key, sources.translation_placeholders) == (
        "playlist_sources_route_missing",
        {"url": "http://trobar.local"},
    )


async def test_a_failed_poll_is_not_a_missing_route(hass, aioclient_mock):
    """A 500 means the route exists and failed once: no Repairs entry."""
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=500)
    aioclient_mock.get(MIRRORS_URL, status=500)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _issue(hass, "server", entry) is None
    assert _issue(hass, "mirrors", entry) is None


async def test_the_entry_goes_once_the_route_answers(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, json=copy.deepcopy(SAMPLE_SERVER_STATUS))
    aioclient_mock.get(MIRRORS_URL, status=404)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _issue(hass, "mirrors", entry) is not None

    # The server is upgraded; the user reloads the integration.
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, json=copy.deepcopy(SAMPLE_SERVER_STATUS))
    aioclient_mock.get(MIRRORS_URL, json=copy.deepcopy(SAMPLE_MIRRORS))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, "mirrors", entry) is None


async def test_removing_the_server_removes_its_repairs(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=404)
    aioclient_mock.get(MIRRORS_URL, status=404)
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=404)
    aioclient_mock.get(PLAYLISTS_URL, status=404)
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _issue(hass, "server", entry) is not None
    assert _issue(hass, "playlist_sources", entry) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, "server", entry) is None
    assert _issue(hass, "mirrors", entry) is None
    assert _issue(hass, "playlist_sources", entry) is None
