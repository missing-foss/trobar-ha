# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Two Trobar servers in one Home Assistant, the 1.1 -> 1.2 registry
migration that makes that possible, and a server too old for the server
route (trobar-ha#20)."""

import copy

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_TOKEN, CONF_URL, STATE_OFF
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN

from .test_sensor import (
    DEVICES_URL,
    MIRRORS_URL,
    PHONE_DEVICE,
    PLAYLIST_SOURCES_URL,
    PLAYLISTS_URL,
    SAMPLE_MIRRORS,
    SAMPLE_PLAYLIST_SOURCES,
    SAMPLE_PLAYLISTS,
    SAMPLE_SERVER_STATUS,
    SERVER_URL,
    _registry_device,
)

OTHER = "http://other.local"


def _mock_server(aioclient_mock, base: str, devices: list) -> None:
    aioclient_mock.get(f"{base}/api/integrations/devices", json=copy.deepcopy(devices))
    aioclient_mock.get(
        f"{base}/api/integrations/server", json=copy.deepcopy(SAMPLE_SERVER_STATUS)
    )
    aioclient_mock.get(
        f"{base}/api/integrations/mirrors", json=copy.deepcopy(SAMPLE_MIRRORS)
    )
    aioclient_mock.get(
        f"{base}/api/integrations/playlist-sources",
        json=copy.deepcopy(SAMPLE_PLAYLIST_SOURCES),
    )
    aioclient_mock.get(
        f"{base}/api/integrations/playlists", json=copy.deepcopy(SAMPLE_PLAYLISTS)
    )


def _entry(base: str, minor_version: int = 2) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=base,
        minor_version=minor_version,
        data={CONF_URL: base, CONF_API_TOKEN: "abc123"},
    )


async def _set_up(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entity_count(hass, entry: MockConfigEntry) -> int:
    return len(er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id))


async def test_two_servers_with_the_same_device_id_each_keep_their_own(
    hass, aioclient_mock
):
    """Device id 1 exists on both servers. Each entry gets its own HA
    device and the full set of entities, none dropped as duplicates."""
    _mock_server(aioclient_mock, "http://trobar.local", [PHONE_DEVICE])
    _mock_server(aioclient_mock, OTHER, [{**PHONE_DEVICE, "name": "Other Phone"}])
    first, second = _entry("http://trobar.local"), _entry(OTHER)
    await _set_up(hass, first)
    await _set_up(hass, second)

    assert _entity_count(hass, first) == _entity_count(hass, second) > 0
    phones = {
        _registry_device(hass, (DOMAIN, f"{e.entry_id}_1")).name
        for e in (first, second)
    }
    assert phones == {"Test Phone", "Other Phone"}


async def test_removing_a_device_on_one_server_leaves_the_other_alone(
    hass, aioclient_mock
):
    _mock_server(aioclient_mock, "http://trobar.local", [PHONE_DEVICE])
    _mock_server(aioclient_mock, OTHER, [PHONE_DEVICE])
    first, second = _entry("http://trobar.local"), _entry(OTHER)
    await _set_up(hass, first)
    await _set_up(hass, second)

    aioclient_mock.clear_requests()
    _mock_server(aioclient_mock, "http://trobar.local", [])
    _mock_server(aioclient_mock, OTHER, [PHONE_DEVICE])
    await first.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert _registry_device(hass, (DOMAIN, f"{first.entry_id}_1")) is None
    assert _registry_device(hass, (DOMAIN, f"{second.entry_id}_1")) is not None


async def test_an_existing_install_is_migrated_in_place(hass, aioclient_mock):
    """Registered under 1.1 (unscoped ids): after setup, the same entity ids
    and the same HA device, under the scoped keys. Nothing is recreated, so
    history and the automations naming them carry over."""
    _mock_server(aioclient_mock, "http://trobar.local", [PHONE_DEVICE])
    entry = _entry("http://trobar.local", minor_version=1)
    entry.add_to_hass(hass)
    device_registry, entity_registry = dr.async_get(hass), er.async_get(hass)
    phone = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "1")}, name="Test Phone"
    )
    server = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="Trobar Server",
    )
    pending = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "1_pending_tracks",
        config_entry=entry,
        device_id=phone.id,
        suggested_object_id="test_phone_pending_tracks",
    )
    reachable = entity_registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "server_reachable",
        config_entry=entry,
        device_id=server.id,
        suggested_object_id="trobar_server_reachable",
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 2
    assert (
        entity_registry.async_get(pending.entity_id).unique_id
        == f"{entry.entry_id}_1_pending_tracks"
    )
    assert (
        entity_registry.async_get(reachable.entity_id).unique_id
        == f"{entry.entry_id}_server_reachable"
    )
    assert device_registry.async_get(phone.id).identifiers == {
        (DOMAIN, f"{entry.entry_id}_1")
    }
    assert device_registry.async_get(server.id).identifiers == {
        (DOMAIN, entry.entry_id)
    }
    # The control: the platform now uses the migrated entity, not a new one.
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_1_pending_tracks"
        )
        == pending.entity_id
    )
    assert hass.states.get(pending.entity_id).state == "10"


async def test_two_entries_both_registered_device_1_each_end_with_their_own(
    hass, aioclient_mock
):
    """Both servers had a device 1 under 1.1. What that left in the device
    registry depends on the core, so this asserts both shapes, chosen by
    what the registry actually did rather than by a version string:

    - a device per entry (2026.8): each is migrated to its entry's
      scoped identifier;
    - one device shared by both entries (2026.3, the floor): it is left
      as it was, since neither entry can claim it, and each entry gets a
      device of its own under the scoped identifier on setup, carrying
      that entry's entities.
    """
    _mock_server(aioclient_mock, "http://trobar.local", [PHONE_DEVICE])
    _mock_server(aioclient_mock, OTHER, [PHONE_DEVICE])
    first, second = (
        _entry("http://trobar.local", minor_version=1),
        _entry(OTHER, minor_version=1),
    )
    first.add_to_hass(hass)
    second.add_to_hass(hass)
    device_registry = dr.async_get(hass)
    mine = device_registry.async_get_or_create(
        config_entry_id=first.entry_id, identifiers={(DOMAIN, "1")}
    )
    theirs = device_registry.async_get_or_create(
        config_entry_id=second.entry_id, identifiers={(DOMAIN, "1")}
    )
    shared = mine.id == theirs.id
    if shared:  # the control for this branch: the core really did share it
        assert device_registry.async_get(mine.id).config_entries == {
            first.entry_id,
            second.entry_id,
        }

    # Setting up one entry loads the integration, which sets up both.
    await _set_up_existing(hass, first)
    assert second.state is ConfigEntryState.LOADED

    entity_registry = er.async_get(hass)
    for entry in (first, second):
        own = _registry_device(hass, (DOMAIN, f"{entry.entry_id}_1"))
        assert own is not None
        pending = entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_1_pending_tracks"
        )
        assert entity_registry.async_get(pending).device_id == own.id

    if shared:
        assert device_registry.async_get(mine.id).identifiers == {(DOMAIN, "1")}
    else:
        assert device_registry.async_get(mine.id).identifiers == {
            (DOMAIN, f"{first.entry_id}_1")
        }
        assert device_registry.async_get(theirs.id).identifiers == {
            (DOMAIN, f"{second.entry_id}_1")
        }


async def _set_up_existing(hass, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_server_without_the_server_route_sets_up_with_device_sensors_only(
    hass, aioclient_mock, caplog
):
    """2.8.1: /api/integrations/server is a 404. The entry loads (no
    endless ConfigEntryNotReady retry), the per-device sensors are there,
    and the server device's entities are not -- skipped, not crashed: a
    platform that raises while adding them leaves the same registry, and
    only its logged error tells the two apart."""
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=404)
    aioclient_mock.get(MIRRORS_URL, status=404)
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=404)
    aioclient_mock.get(PLAYLISTS_URL, status=404)
    entry = _entry("http://trobar.local")
    await _set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    entity_registry = er.async_get(hass)
    platforms = {
        e.domain
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    assert platforms == {"sensor"}
    assert entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_1_pending_tracks"
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_server_version"
        )
        is None
    )
    platform_errors = [
        r.getMessage()
        for r in caplog.records
        if r.levelname == "ERROR" and r.name.startswith("homeassistant.components.")
    ]
    assert platform_errors == []


async def test_an_unreachable_server_route_at_startup_keeps_the_entities(
    hass, aioclient_mock
):
    """A 500 is not a 404: the route exists and failed this once, so the
    entities stay and read what they know -- reachable reads off."""
    aioclient_mock.get(DEVICES_URL, json=[copy.deepcopy(PHONE_DEVICE)])
    aioclient_mock.get(SERVER_URL, status=500)
    aioclient_mock.get(MIRRORS_URL, json=copy.deepcopy(SAMPLE_MIRRORS))
    aioclient_mock.get(
        PLAYLIST_SOURCES_URL, json=copy.deepcopy(SAMPLE_PLAYLIST_SOURCES)
    )
    aioclient_mock.get(PLAYLISTS_URL, json=copy.deepcopy(SAMPLE_PLAYLISTS))
    entry = _entry("http://trobar.local")
    await _set_up(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    reachable = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_server_reachable"
    )
    assert hass.states.get(reachable).state == STATE_OFF


async def test_a_devices_route_failure_still_retries_the_entry(hass, aioclient_mock):
    """The device list stays the first_refresh: an unreachable server is
    still ConfigEntryNotReady, retried, not set up with nothing."""
    aioclient_mock.get(DEVICES_URL, status=500)
    entry = _entry("http://trobar.local")
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
