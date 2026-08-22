# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for playlist-mirror health (trobar-ha#32, trobar-server#506).

Built against the documented payload shape rather than a captured one --
trobar-ha#33 is the issue for a real redacted response, still open. The
payloads below deliberately cover the cases #33 lists as worth capturing
beyond the happy path, since each is somewhere an implementation can go
wrong: a null last_written_at, a sink enabled nowhere, a truncated
worklist, and several sinks failing at once.
"""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.trobar.const import DOMAIN

from .test_sensor import MIRRORS_URL, _setup_entry

# One sink dead (subsonic), one odd playlist elsewhere (jellyfin), one
# sink configured nowhere (emby), and a mirror that has never once
# written successfully (last_written_at: null).
FAILING_MIRRORS = {
    "mirrors_failing": 3,
    "by_sink": {
        "filesystem": {"enabled": 4, "failing": 0},
        "subsonic": {"enabled": 6, "failing": 2},
        "jellyfin": {"enabled": 6, "failing": 1},
        "emby": {"enabled": 0, "failing": 0},
    },
    "failing": [
        {
            "playlist_id": 12,
            "title": "Road Trip",
            "sink": "subsonic",
            "error_code": "unreachable",
            "last_written_at": "2026-07-30T09:14:02Z",
        },
        {
            "playlist_id": 13,
            "title": "Focus",
            "sink": "subsonic",
            "error_code": "unreachable",
            "last_written_at": None,
        },
        {
            "playlist_id": 40,
            "title": "Kids",
            "sink": "jellyfin",
            "error_code": "no_target_matches",
            "last_written_at": "2026-07-28T22:00:00Z",
        },
    ],
    "failing_truncated": False,
}

# More pairs failing than the 50-entry array holds. The counts stay
# exact; only the list is short -- the case that breaks any consumer
# counting failing[] instead of reading mirrors_failing.
TRUNCATED_MIRRORS = {
    "mirrors_failing": 137,
    "by_sink": {
        "filesystem": {"enabled": 0, "failing": 0},
        "subsonic": {"enabled": 140, "failing": 137},
        "jellyfin": {"enabled": 0, "failing": 0},
        "emby": {"enabled": 0, "failing": 0},
    },
    "failing": [
        {
            "playlist_id": i,
            "title": f"Playlist {i}",
            "sink": "subsonic",
            "error_code": "unreachable",
            "last_written_at": None,
        }
        for i in range(50)
    ],
    "failing_truncated": True,
}


def _sensor_id(hass) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, "server_mirrors_failing"
    )


def _problem_id(hass) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "server_mirrors_problem"
    )


async def test_healthy_instance_reads_zero_and_no_problem(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    assert hass.states.get(_sensor_id(hass)).state == "0"
    assert hass.states.get(_problem_id(hass)).state == STATE_OFF


async def test_failing_mirrors_surface_count_and_problem(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    assert hass.states.get(_sensor_id(hass)).state == "3"
    assert hass.states.get(_problem_id(hass)).state == STATE_ON


async def test_worklist_and_breakdown_travel_as_attributes(hass, aioclient_mock):
    """State is capped at 255 chars by HA, so a 50-entry worklist has to
    live in attributes -- and the per-sink breakdown with it."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    attrs = hass.states.get(_sensor_id(hass)).attributes
    assert attrs["by_sink"]["subsonic"] == {"enabled": 6, "failing": 2}
    assert attrs["failing_truncated"] is False
    assert [entry["playlist_id"] for entry in attrs["failing"]] == [12, 13, 40]


async def test_by_sink_failing_sums_to_the_exact_total(hass, aioclient_mock):
    """trobar-server#506's documented invariant. Worth asserting here
    because the sensor's state and its attributes come from the same
    payload -- if they ever disagreed, an automation on the state and a
    dashboard on the attributes would tell the operator different
    things."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    state = hass.states.get(_sensor_id(hass))
    assert sum(s["failing"] for s in state.attributes["by_sink"].values()) == int(
        state.state
    )


async def test_a_sink_enabled_nowhere_is_reported_not_omitted(hass, aioclient_mock):
    """The normal state for most installs on at least one sink (#33).
    It must still appear, so a dashboard can say "emby: not configured"
    rather than silently omitting the row."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    by_sink = hass.states.get(_sensor_id(hass)).attributes["by_sink"]
    assert by_sink["emby"] == {"enabled": 0, "failing": 0}


async def test_never_written_mirror_keeps_its_null(hass, aioclient_mock):
    """last_written_at is null for a mirror that has never successfully
    written (#33). It must survive as None rather than being coerced to
    a string or dropped -- "how long has this been broken" is the
    operator's actual question, and null is a real answer to it."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    failing = hass.states.get(_sensor_id(hass)).attributes["failing"]
    never_written = next(e for e in failing if e["playlist_id"] == 13)
    assert never_written["last_written_at"] is None


async def test_error_codes_pass_through_raw(hass, aioclient_mock):
    """trobar-server#428 made these language-independent machine codes.
    They travel raw; HA does not localise attributes, so a translation
    here would have no surface to render on."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    failing = hass.states.get(_sensor_id(hass)).attributes["failing"]
    assert {e["error_code"] for e in failing} == {"unreachable", "no_target_matches"}


async def test_truncated_worklist_does_not_undercount(hass, aioclient_mock):
    """The cap bites hardest on exactly the installs that most need the
    alert -- one dead target fails every playlist pointed at it. The
    state must be the exact 137, not the 50 entries the array holds."""
    await _setup_entry(hass, aioclient_mock, [], mirrors=TRUNCATED_MIRRORS)

    state = hass.states.get(_sensor_id(hass))
    assert state.state == "137"
    assert len(state.attributes["failing"]) == 50
    assert state.attributes["failing_truncated"] is True
    assert hass.states.get(_problem_id(hass)).state == STATE_ON


async def test_entities_are_skipped_on_a_server_older_than_2_12(hass, aioclient_mock):
    """The route's floor is 2.12.0 while the integration supports 2.8.0+,
    so a 404 here is a supported configuration rather than a fault. Setup
    must still succeed, and the two mirror entities must be absent
    entirely -- an entity that could only ever read unavailable looks
    like a broken integration."""
    entry = await _setup_entry(hass, aioclient_mock, [], mirrors_status=404)

    assert entry.state is ConfigEntryState.LOADED
    assert _sensor_id(hass) is None
    assert _problem_id(hass) is None
    assert entry.runtime_data.mirrors is None


async def test_the_404_log_line_does_not_assert_a_cause(hass, aioclient_mock, caplog):
    """This is the only place a 404 silently changes what gets set up, and
    _request_json maps ANY 404 to TrobarServerTooOldError -- so "old
    server" is the likely cause, not an established one. A proxy whose
    path allowlist missed the newer route 404s exactly this path and
    reads identically. The message must name both, or it sends whoever
    is grepping for the missing entities after the wrong problem.
    """
    await _setup_entry(hass, aioclient_mock, [], mirrors_status=404)

    line = next(
        r.getMessage() for r in caplog.records if "mirrors route" in r.getMessage()
    )
    assert "2.12.0" in line
    assert "proxy" in line
    assert "skipping mirror health entities" in line.lower()


async def test_other_entities_survive_a_missing_mirrors_route(hass, aioclient_mock):
    """The point of a third coordinator: mirrors 404ing must not take the
    server or device entities with it."""
    await _setup_entry(hass, aioclient_mock, [], mirrors_status=404)

    reachable = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, "server_reachable"
    )
    assert hass.states.get(reachable).state == STATE_ON


async def test_unreachable_server_keeps_the_entities_but_unavailable(
    hass, aioclient_mock
):
    """A failed poll is NOT the same as an absent route. The entities stay
    (the server may come back) and read unavailable, which is true --
    whether mirrors are failing genuinely is unknown while the server
    can't be reached."""
    entry = await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)
    assert hass.states.get(_sensor_id(hass)).state == "3"

    aioclient_mock.clear_requests()
    aioclient_mock.get(MIRRORS_URL, status=500)
    await entry.runtime_data.mirrors.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_sensor_id(hass)).state == STATE_UNAVAILABLE
    assert hass.states.get(_problem_id(hass)).state == STATE_UNAVAILABLE


async def test_a_failed_poll_does_not_mark_the_route_unsupported(hass, aioclient_mock):
    """`supported` must only ever go False on a 404. Letting a transient
    failure clear it would silently drop the entities until the next
    reload -- the same class of silent degradation the rest of this
    integration is careful about."""
    entry = await _setup_entry(hass, aioclient_mock, [], mirrors=FAILING_MIRRORS)

    aioclient_mock.clear_requests()
    aioclient_mock.get(MIRRORS_URL, status=500)
    await entry.runtime_data.mirrors.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.mirrors.supported is True
