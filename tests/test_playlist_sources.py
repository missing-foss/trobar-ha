# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for playlist-source health: the failing-sources sensor and the
problem binary sensor, from GET /api/integrations/playlist-sources.

The payloads follow the route as the server builds it: exact counts, a
capped `alerting` worklist with its truncation flag, `failing_since` in
ISO 8601 with its zone, and raw reason codes."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.helpers import entity_registry as er

from custom_components.trobar.const import DOMAIN

from .test_sensor import PLAYLIST_SOURCES_URL, _setup_entry, _uid

# Three alerting sources of three kinds, and two more failing that don't
# alert yet (fewer than 3 runs, or less than 12 hours).
ALERTING_SOURCES = {
    "sources_total": 9,
    "sources_failing": 5,
    "sources_alerting": 3,
    "alerting": [
        {
            "kind": "linked_account",
            "provider": "tidal",
            "account": "carol",
            "failing_since": "2026-08-02T05:35:00Z",
            "runs": 371,
            "reason": "http_404",
        },
        {
            "kind": "member_listing",
            "provider": "jellyfin",
            "account": "bob",
            "failing_since": "2026-11-02T18:00:00Z",
            "runs": 3,
            "reason": "not_found",
        },
        {
            "kind": "public_link",
            "provider": "public",
            "account": "Road trip mix",
            "failing_since": "2026-11-01T09:00:00Z",
            "runs": 4,
            "reason": "unavailable",
        },
    ],
    "alerting_truncated": False,
}

# More alerting than the worklist holds: the count stays exact.
TRUNCATED_SOURCES = {
    "sources_total": 80,
    "sources_failing": 72,
    "sources_alerting": 72,
    "alerting": [
        {
            "kind": "linked_account",
            "provider": "tidal",
            "account": f"member{i}",
            "failing_since": "2026-11-01T00:00:00Z",
            "runs": 5,
            "reason": "token_rejected",
        }
        for i in range(50)
    ],
    "alerting_truncated": True,
}

# Failing, but nothing alerts yet: one bad night.
FAILING_NOT_ALERTING = {
    "sources_total": 4,
    "sources_failing": 2,
    "sources_alerting": 0,
    "alerting": [],
    "alerting_truncated": False,
}


def _sensor_id(hass) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, _uid(hass, "server_playlist_sources_failing")
    )


def _problem_id(hass) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, _uid(hass, "server_playlist_sources_problem")
    )


async def test_healthy_sources_read_zero_and_no_problem(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [])

    state = hass.states.get(_sensor_id(hass))
    assert state.state == "0"
    assert state.attributes["sources_total"] == 3
    assert hass.states.get(_problem_id(hass)).state == STATE_OFF


async def test_alerting_sources_surface_count_and_problem(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [], playlist_sources=ALERTING_SOURCES)

    assert hass.states.get(_sensor_id(hass)).state == "3"
    assert hass.states.get(_problem_id(hass)).state == STATE_ON


async def test_the_worklist_and_failing_count_travel_as_attributes(
    hass, aioclient_mock
):
    """The reason codes pass through raw, as mirrors' error codes do, and
    `failing_since` keeps its zone."""
    await _setup_entry(hass, aioclient_mock, [], playlist_sources=ALERTING_SOURCES)

    attrs = hass.states.get(_sensor_id(hass)).attributes
    assert attrs["sources_failing"] == 5
    assert attrs["alerting_truncated"] is False
    assert [(s["kind"], s["provider"], s["reason"]) for s in attrs["alerting"]] == [
        ("linked_account", "tidal", "http_404"),
        ("member_listing", "jellyfin", "not_found"),
        ("public_link", "public", "unavailable"),
    ]
    assert attrs["alerting"][0]["failing_since"] == "2026-08-02T05:35:00Z"


async def test_failing_without_alerting_is_no_problem(hass, aioclient_mock):
    """The server's alert rule is followed, not second-guessed: sources that
    failed a run or two are an attribute for an early warning, not a page."""
    await _setup_entry(hass, aioclient_mock, [], playlist_sources=FAILING_NOT_ALERTING)

    state = hass.states.get(_sensor_id(hass))
    assert state.state == "0"
    assert state.attributes["sources_failing"] == 2
    assert hass.states.get(_problem_id(hass)).state == STATE_OFF


async def test_a_truncated_worklist_does_not_undercount(hass, aioclient_mock):
    await _setup_entry(hass, aioclient_mock, [], playlist_sources=TRUNCATED_SOURCES)

    state = hass.states.get(_sensor_id(hass))
    assert state.state == "72"
    assert len(state.attributes["alerting"]) == 50
    assert state.attributes["alerting_truncated"] is True
    assert hass.states.get(_problem_id(hass)).state == STATE_ON


async def test_the_problem_reads_the_count_not_the_list(hass, aioclient_mock):
    """A count above zero with the list cut to nothing is still a problem:
    the count is the exact one."""
    await _setup_entry(
        hass,
        aioclient_mock,
        [],
        playlist_sources={
            **ALERTING_SOURCES,
            "alerting": [],
            "alerting_truncated": True,
        },
    )

    assert hass.states.get(_problem_id(hass)).state == STATE_ON
    assert hass.states.get(_sensor_id(hass)).state == "3"


async def test_entities_are_skipped_on_a_server_without_the_route(hass, aioclient_mock):
    entry = await _setup_entry(hass, aioclient_mock, [], playlist_sources_status=404)

    assert entry.state is ConfigEntryState.LOADED
    assert _sensor_id(hass) is None
    assert _problem_id(hass) is None
    assert entry.runtime_data.playlist_sources is None


async def test_the_404_log_line_names_both_causes(hass, aioclient_mock, caplog):
    await _setup_entry(hass, aioclient_mock, [], playlist_sources_status=404)

    line = next(
        r.getMessage()
        for r in caplog.records
        if "playlist sources route" in r.getMessage()
    )
    assert "predates" in line
    assert "proxy" in line
    assert "skipping playlist-source health entities" in line.lower()


async def test_other_entities_survive_a_missing_route(hass, aioclient_mock):
    """Its own coordinator: a 404 here takes neither the server entities
    nor the mirror ones with it."""
    await _setup_entry(hass, aioclient_mock, [], playlist_sources_status=404)

    registry = er.async_get(hass)
    reachable = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, _uid(hass, "server_reachable")
    )
    mirrors = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, _uid(hass, "server_mirrors_problem")
    )
    assert hass.states.get(reachable).state == STATE_ON
    assert hass.states.get(mirrors).state == STATE_OFF


async def test_a_failed_poll_keeps_the_entities_but_unavailable(hass, aioclient_mock):
    """A 500 is not an absent route: the entities stay and read unavailable,
    and the route stays supported."""
    entry = await _setup_entry(
        hass, aioclient_mock, [], playlist_sources=ALERTING_SOURCES
    )
    assert hass.states.get(_sensor_id(hass)).state == "3"

    aioclient_mock.clear_requests()
    aioclient_mock.get(PLAYLIST_SOURCES_URL, status=500)
    await entry.runtime_data.playlist_sources.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_sensor_id(hass)).state == STATE_UNAVAILABLE
    assert hass.states.get(_problem_id(hass)).state == STATE_UNAVAILABLE
    assert entry.runtime_data.playlist_sources.supported is True


async def test_a_failure_elsewhere_leaves_these_entities_alone(hass, aioclient_mock):
    """The other way round: the mirrors route failing must not make these
    unavailable."""
    entry = await _setup_entry(
        hass, aioclient_mock, [], playlist_sources=ALERTING_SOURCES
    )

    aioclient_mock.clear_requests()
    aioclient_mock.get("http://trobar.local/api/integrations/mirrors", status=500)
    await entry.runtime_data.mirrors.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(_sensor_id(hass)).state == "3"
    assert hass.states.get(_problem_id(hass)).state == STATE_ON
