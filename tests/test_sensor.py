# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Trobar sensor platform (trobar-ha#5)."""

import copy

from homeassistant.const import CONF_API_TOKEN, CONF_URL, EntityCategory
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN

DEVICES_URL = "http://trobar.local/api/integrations/devices"
SERVER_URL = "http://trobar.local/api/integrations/server"
MIRRORS_URL = "http://trobar.local/api/integrations/mirrors"
PLAYLIST_SOURCES_URL = "http://trobar.local/api/integrations/playlist-sources"
PLAYLISTS_URL = "http://trobar.local/api/integrations/playlists"

# trobar-ha#25: __init__.py's first refresh now fetches both endpoints,
# so every test that sets up a full config entry needs this mocked too --
# a fixed default here, overridable per-test the same way DEVICES_URL is.
SAMPLE_SERVER_STATUS = {
    "version": "2.9.0",
    "track_count": 100,
    "total_bytes": 5_000_000_000,
    "scan_running": False,
    "last_scan_at": "2026-07-30 12:00:00",
}

# trobar-ha#32: a third endpoint, so a third default here for the same
# reason. The healthy shape is the default because most tests don't care
# about mirrors; tests/test_mirrors.py overrides it with the failing and
# edge-case payloads.
SAMPLE_MIRRORS = {
    "mirrors_failing": 0,
    "by_sink": {
        "filesystem": {"enabled": 4, "failing": 0},
        "subsonic": {"enabled": 6, "failing": 0},
        "jellyfin": {"enabled": 6, "failing": 0},
        "emby": {"enabled": 0, "failing": 0},
    },
    "failing": [],
    "failing_truncated": False,
}

# The healthy playlist-sources shape, the default for the same reason as
# SAMPLE_MIRRORS; tests/test_playlist_sources.py overrides it.
SAMPLE_PLAYLIST_SOURCES = {
    "sources_total": 3,
    "sources_failing": 0,
    "sources_alerting": 0,
    "alerting": [],
    "alerting_truncated": False,
}

# Device playlists (trobar-ha#19), the default for the same reason again;
# tests/test_playlists.py overrides it. The phone has three playlists, one
# of them private, so the server leaves its title out; the watch has none:
# an empty list, not an absent device.
SAMPLE_PLAYLISTS = {
    "playlists_total": 5,
    "playlists_with_gaps": 1,
    "devices": [
        {
            "device_id": 1,
            "name": "Test Phone",
            "playlists_count": 3,
            "playlists": [
                {
                    "playlist_id": 3,
                    "title": "Morning run",
                    "private": False,
                    "tracks": 20,
                    "matched": 20,
                    "available": 100,
                    "has_gaps": False,
                },
                {
                    "playlist_id": 7,
                    "title": "Kitchen radio",
                    "private": False,
                    "tracks": 40,
                    "matched": 30,
                    "available": 75,
                    "has_gaps": True,
                },
                {
                    "playlist_id": 9,
                    "title": None,
                    "private": True,
                    "tracks": 10,
                    "matched": 5,
                    "available": 50,
                    "has_gaps": False,
                },
            ],
            "playlists_truncated": False,
        },
        {
            "device_id": 5,
            "name": "Test Watch",
            "playlists_count": 0,
            "playlists": [],
            "playlists_truncated": False,
        },
    ],
}

# A regular phone: fully populated, nothing null.
PHONE_DEVICE = {
    "id": 1,
    "name": "Test Phone",
    "device_type": "phone",
    "owner_user_id": 1,
    "owner_username": "alice",
    "is_own": True,
    "is_pinned": False,
    "max_size_bytes": 150000000000,
    "reported_free_bytes": 300000000000,
    "reported_total_bytes": 512000000000,
    "free_bytes_reported_at": "2026-07-28 21:00:00",
    # Music in the sync folder that Trobar did not put there. It counts
    # against max_size_bytes, which is a limit on the FOLDER rather than on
    # Trobar's own share of it -- so this phone is 40 GB into its 150 GB
    # before Trobar has synced anything.
    "reported_foreign_bytes": 40000000000,
    "foreign_bytes_reported_at": "2026-07-28 21:00:00",
    "last_seen_at": "2026-07-28 21:00:00",
    "created_at": "2026-01-01 00:00:00",
    "source_of_truth": "device",
    "transcode_format": None,
    "artist_images": "small",
    "unknown_track_count": 223,
    "autofit": {"enabled": False, "percent": 100},
    "sync_status": {"last_synced_at": "2026-07-28 20:00:00", "pending_count": 10},
}

# A delegated (not owned) watch: never synced, and permanently no storage
# data at all -- the case that must NOT read as a bug. The Garmin client
# only ever calls changes/file/ack, so it never reports storage and never
# uploads a manifest; every storage field here is null BY DESIGN and stays
# null forever, rather than being data that has not arrived yet.
WATCH_DEVICE = {
    "id": 5,
    "name": "Test Watch",
    "device_type": "watch",
    "owner_user_id": 2,
    "owner_username": "bob",
    "is_own": False,
    "is_pinned": False,
    "max_size_bytes": None,
    "reported_free_bytes": None,
    "reported_total_bytes": None,
    "free_bytes_reported_at": None,
    # None, not 0: never measured is a different claim from measured empty,
    # and this device will never measure. Substituting zero here would make
    # the fixture assert that a watch reports an empty folder, which is the
    # exact misreading the server keeps these two apart to prevent.
    "reported_foreign_bytes": None,
    "foreign_bytes_reported_at": None,
    "last_seen_at": "2026-07-28 21:00:00",
    "created_at": "2026-01-01 00:00:00",
    "source_of_truth": "server",
    "transcode_format": "mp3_128",
    "artist_images": None,
    "unknown_track_count": None,
    "autofit": {"enabled": False, "percent": 100},
    "sync_status": {"last_synced_at": None, "pending_count": 1},
}


async def _setup_entry(
    hass,
    aioclient_mock,
    devices,
    server_status=SAMPLE_SERVER_STATUS,
    mirrors=SAMPLE_MIRRORS,
    mirrors_status=None,
    playlist_sources=SAMPLE_PLAYLIST_SOURCES,
    playlist_sources_status=None,
    playlists=SAMPLE_PLAYLISTS,
    playlists_status=None,
) -> MockConfigEntry:
    aioclient_mock.get(DEVICES_URL, json=copy.deepcopy(devices))
    aioclient_mock.get(SERVER_URL, json=copy.deepcopy(server_status))
    if mirrors_status is not None:
        # For the server-too-old / unreachable cases, where the route
        # answers a status rather than a payload (trobar-ha#32).
        aioclient_mock.get(MIRRORS_URL, status=mirrors_status)
    else:
        aioclient_mock.get(MIRRORS_URL, json=copy.deepcopy(mirrors))
    if playlist_sources_status is not None:
        aioclient_mock.get(PLAYLIST_SOURCES_URL, status=playlist_sources_status)
    else:
        aioclient_mock.get(PLAYLIST_SOURCES_URL, json=copy.deepcopy(playlist_sources))
    if playlists_status is not None:
        aioclient_mock.get(PLAYLISTS_URL, status=playlists_status)
    else:
        aioclient_mock.get(PLAYLISTS_URL, json=copy.deepcopy(playlists))
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "abc123"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _uid(hass, key: str) -> str:
    """`key` scoped by the one Trobar config entry these tests set up, as
    the integration scopes every unique id (const.entity_unique_id)."""
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    return f"{entry.entry_id}_{key}"


def _registry_device(hass, identifier: tuple[str, str]):
    """The registered device with `identifier`, without the lookup newer
    cores deprecate (identifiers are no longer unique across entries)."""
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_devices"):
        found = registry.async_get_devices(identifiers={identifier})
        assert len(found) <= 1, found
        return found[0] if found else None
    return registry.async_get_device(identifiers={identifier})


def _device_identifier(hass, device_id: int) -> tuple[str, str]:
    """A Trobar device's identifier within the one config entry."""
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    return (DOMAIN, f"{entry.entry_id}_{device_id}")


def _entity_id(hass, device_id: int, key: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, _uid(hass, f"{device_id}_{key}")
    )


def _server_entity_id(hass, key: str) -> str | None:
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, _uid(hass, f"server_{key}"))


async def test_populated_device_sensor_values(hass, aioclient_mock):
    """A fully-populated device's sensors read its values directly."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    assert hass.states.get(_entity_id(hass, 1, "pending_tracks")).state == "10"
    assert hass.states.get(_entity_id(hass, 1, "unknown_tracks")).state == "223"
    assert hass.states.get(_entity_id(hass, 1, "free_space")).state != "unavailable"


async def test_never_synced_reads_as_unknown_not_unavailable(hass, aioclient_mock):
    """last_synced_at: null means 'never', which is a real value -- the
    sensor must stay available, just with no timestamp yet."""
    await _setup_entry(hass, aioclient_mock, [WATCH_DEVICE])

    state = hass.states.get(_entity_id(hass, 5, "last_synced"))
    assert state.state == "unknown"


async def test_unknown_track_count_null_is_not_zero(hass, aioclient_mock):
    """unknown_track_count: null must not be coerced into the state "0"."""
    await _setup_entry(hass, aioclient_mock, [WATCH_DEVICE])

    state = hass.states.get(_entity_id(hass, 5, "unknown_tracks"))
    assert state.state == "unknown"
    assert state.state != "0"


async def test_watch_storage_sensors_are_unavailable_not_unknown(hass, aioclient_mock):
    """A device that structurally never reports storage -- the Garmin watch,
    which only ever calls changes/file/ack -- must read UNAVAILABLE, not get
    stuck at "unknown" with no explanation."""
    await _setup_entry(hass, aioclient_mock, [WATCH_DEVICE])

    assert hass.states.get(_entity_id(hass, 5, "free_space")).state == "unavailable"
    assert hass.states.get(_entity_id(hass, 5, "total_space")).state == "unavailable"


async def test_delegated_device_exposes_ownership_attributes(hass, aioclient_mock):
    """A device belonging to another household member carries is_own and
    owner_username as attributes, so a card can distinguish it."""
    await _setup_entry(hass, aioclient_mock, [WATCH_DEVICE])

    state = hass.states.get(_entity_id(hass, 5, "pending_tracks"))
    assert state.attributes["is_own"] is False
    assert state.attributes["owner_username"] == "bob"


async def test_device_name_is_never_owner_suffixed(hass, aioclient_mock):
    """#17's decision: Option A (touching the device name) was explicitly
    declined, for both an owned and a delegated device -- names stay
    exactly as Trobar reports them regardless of ownership."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])

    assert _registry_device(hass, _device_identifier(hass, 1)).name == "Test Phone"
    assert _registry_device(hass, _device_identifier(hass, 5)).name == "Test Watch"


async def test_owner_sensor_reports_username_for_multiple_owners(hass, aioclient_mock):
    """#17's decided shape: a diagnostic sensor per device, state = the
    owner's username. Synthesised as a multi-owner response since the #2
    sample is single-user and can't exercise this."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])

    assert hass.states.get(_entity_id(hass, 1, "owner")).state == "alice"
    assert hass.states.get(_entity_id(hass, 5, "owner")).state == "bob"


async def test_owner_sensor_is_diagnostic(hass, aioclient_mock):
    """Diagnostic category, not a regular sensor --'s decision,
    chosen over duplicating the value across every sibling sensor's
    attributes precisely so it appears under Diagnostics with its own
    stable entity_id."""
    await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    registry = er.async_get(hass)
    entry = registry.async_get(_entity_id(hass, 1, "owner"))
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_owner_sensor_follows_transfer_on_next_refresh(hass, aioclient_mock):
    """trobar-server#442 device-to-device transfer changes owner_user_id
    server-side at runtime -- the owner sensor must follow the coordinator's
    refresh rather than freezing whatever it read at setup."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert hass.states.get(_entity_id(hass, 1, "owner")).state == "alice"

    transferred = copy.deepcopy(PHONE_DEVICE)
    transferred["owner_user_id"] = 2
    transferred["owner_username"] = "bob"
    transferred["is_own"] = False
    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[transferred])
    await entry.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, 1, "owner")).state == "bob"


async def test_device_removed_from_response_is_removed_from_registry(
    hass, aioclient_mock, caplog
):
    """A device that vanishes from a successful poll (deleted, or
    transferred away -- trobar-server#442) is removed outright, not left
    behind reading unavailable forever. It's looked up without the
    registry call newer cores deprecate, which they report in the log."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])

    assert _registry_device(hass, _device_identifier(hass, 5)) is not None

    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[PHONE_DEVICE])
    await entry.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert _registry_device(hass, _device_identifier(hass, 5)) is None
    assert _entity_id(hass, 5, "pending_tracks") is None
    assert "Detected that custom integration 'trobar' calls" not in caplog.text


async def _remove_by_hand(hass, ws_client, entry, device_entry) -> bool:
    """What the device page's Delete button does."""
    await ws_client.send_json_auto_id(
        {
            "type": "config/device_registry/remove_config_entry",
            "config_entry_id": entry.entry_id,
            "device_id": device_entry.id,
        }
    )
    response = await ws_client.receive_json()
    return response["success"]


async def test_a_listed_device_cannot_be_removed_by_hand(
    hass, aioclient_mock, hass_ws_client
):
    """A device the server still lists stays: removing it by hand would
    only bring it back on the next poll, minus its customisations."""
    assert await async_setup_component(hass, "config", {})
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE, WATCH_DEVICE])
    device_registry = dr.async_get(hass)
    device = _registry_device(hass, _device_identifier(hass, 5))

    assert not await _remove_by_hand(hass, await hass_ws_client(hass), entry, device)
    assert device_registry.async_get(device.id) is not None


async def test_the_server_device_cannot_be_removed_by_hand(
    hass, aioclient_mock, hass_ws_client
):
    """The server device belongs to the config entry, not the device list."""
    assert await async_setup_component(hass, "config", {})
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    device_registry = dr.async_get(hass)
    device = _registry_device(hass, (DOMAIN, entry.entry_id))
    assert device is not None

    assert not await _remove_by_hand(hass, await hass_ws_client(hass), entry, device)
    assert device_registry.async_get(device.id) is not None


async def test_a_leftover_device_can_be_removed_by_hand(
    hass, aioclient_mock, hass_ws_client
):
    """A device of this entry that the server no longer lists, which the
    automatic removal didn't catch, can be deleted from its device page."""
    assert await async_setup_component(hass, "config", {})
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    device_registry = dr.async_get(hass)
    leftover = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={_device_identifier(hass, 5)},
    )

    assert await _remove_by_hand(hass, await hass_ws_client(hass), entry, leftover)
    assert device_registry.async_get(leftover.id) is None


async def test_device_added_in_later_refresh_gets_entities(hass, aioclient_mock):
    """A device that first appears in a later poll (newly enrolled) gets
    its sensors added without a reload."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _entity_id(hass, 5, "pending_tracks") is None

    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, json=[PHONE_DEVICE, WATCH_DEVICE])
    await entry.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, 5, "pending_tracks")) is not None


async def test_whole_poll_failure_makes_entities_unavailable(hass, aioclient_mock):
    """A failed poll (not a single device vanishing) makes every entity
    unavailable -- the coordinator's own mechanism, not per-device logic."""
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])

    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, status=401)
    await entry.runtime_data.devices.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, 1, "pending_tracks")).state == "unavailable"


async def test_unknown_fields_are_tolerated(hass, aioclient_mock):
    """#18: this integration reads specific keys off the response dict
    rather than validating the payload's exact shape, so a field the
    server adds later -- one #455's own gate explicitly allows -- must
    never break setup. Unknown keys go at the top level and inside both
    nested objects in the response: sync_status, which the sensors
    read from, and autofit, which nothing reads yet -- included anyway
    since it's part of the documented shape and a future sensor could
    read it."""
    device = copy.deepcopy(PHONE_DEVICE)
    device["future_top_level_field"] = "surprise"
    device["sync_status"]["future_sync_field"] = 42
    device["autofit"]["future_autofit_field"] = True

    await _setup_entry(hass, aioclient_mock, [device])

    assert hass.states.get(_entity_id(hass, 1, "pending_tracks")).state == "10"
    assert hass.states.get(_entity_id(hass, 1, "unknown_tracks")).state == "223"
    assert hass.states.get(_entity_id(hass, 1, "owner")).state == "alice"
    assert hass.states.get(_entity_id(hass, 1, "free_space")).state != "unavailable"


async def test_server_sensors_read_the_server_status_values(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    assert hass.states.get(_server_entity_id(hass, "version")).state == "2.9.0"
    assert hass.states.get(_server_entity_id(hass, "tracks")).state == "100"
    library_size_state = hass.states.get(_server_entity_id(hass, "library_size"))
    assert library_size_state.state != "unavailable"


async def test_server_last_scan_null_reads_as_unknown_not_unavailable(
    hass, aioclient_mock
):
    """trobar-server#475's own null semantics: last_scan_at is null while
    a scan is running or before the first one ever completes -- a real,
    meaningful value ("no completed scan to report"), not an error."""
    never_scanned = {**SAMPLE_SERVER_STATUS, "last_scan_at": None}
    await _setup_entry(hass, aioclient_mock, [], server_status=never_scanned)

    state = hass.states.get(_server_entity_id(hass, "last_scan"))
    assert state.state == "unknown"


async def test_server_version_sensor_is_diagnostic(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    registry = er.async_get(hass)
    entry = registry.async_get(_server_entity_id(hass, "version"))
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_server_sensors_share_one_device_with_the_binary_sensors_and_button(
    hass, aioclient_mock
):
    await _setup_entry(hass, aioclient_mock, [])

    registry = er.async_get(hass)
    device_ids = {
        registry.async_get(_server_entity_id(hass, key)).device_id
        for key in ("version", "tracks", "library_size", "last_scan")
    }
    device_ids.add(
        registry.async_get(
            registry.async_get_entity_id(
                "binary_sensor", DOMAIN, _uid(hass, "server_reachable")
            )
        ).device_id
    )
    device_ids.add(
        registry.async_get(
            registry.async_get_entity_id(
                "button", DOMAIN, _uid(hass, "server_scan_library")
            )
        ).device_id
    )
    assert len(device_ids) == 1


async def test_server_status_unknown_fields_are_tolerated(hass, aioclient_mock):
    """Same #18 discipline as the devices response -- a field #475 adds
    later must not break setup."""
    status = {**SAMPLE_SERVER_STATUS, "future_field": "surprise"}
    await _setup_entry(hass, aioclient_mock, [], server_status=status)

    assert hass.states.get(_server_entity_id(hass, "version")).state == "2.9.0"
