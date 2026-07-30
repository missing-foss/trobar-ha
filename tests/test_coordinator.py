# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the coordinator's auth-failure handling (trobar-ha#28).

trobar-server#478 started revoking non-admin-minted integration tokens
on upgrade, which makes a 401 mid-poll a real, reachable case rather
than a theoretical one. Before this, a 401 fell into the same
UpdateFailed bucket as a rate limit or a network blip -- retried
forever, with no way for Home Assistant to ever prompt for a new token.
"""

from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN

DEVICES_URL = "http://trobar.local/api/integrations/devices"


def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "abc123"},
    )
    entry.add_to_hass(hass)
    return entry


def _reauth_flow_pending(hass, entry_id: str) -> bool:
    return any(
        flow["context"].get("source") == SOURCE_REAUTH
        and flow["context"].get("entry_id") == entry_id
        for flow in hass.config_entries.flow.async_progress()
    )


async def test_a_401_on_first_setup_starts_a_reauth_flow(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, status=401)
    entry = _entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _reauth_flow_pending(hass, entry.entry_id)


async def test_a_401_after_a_successful_setup_starts_a_reauth_flow(
    hass, aioclient_mock
):
    # Distinct code path from the one above: first-refresh-during-setup
    # propagates ConfigEntryAuthFailed up to config entry setup, which
    # starts reauth; a later scheduled refresh has the coordinator start
    # it directly (see update_coordinator.py's own two call sites this
    # integration relies on). Both must work.
    aioclient_mock.get(DEVICES_URL, json=[])
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert not _reauth_flow_pending(hass, entry.entry_id)

    aioclient_mock.clear_requests()
    aioclient_mock.get(DEVICES_URL, status=401)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert _reauth_flow_pending(hass, entry.entry_id)


async def test_a_429_does_not_start_a_reauth_flow(hass, aioclient_mock):
    # The control case trobar-ha#28 explicitly calls out: rate-limiting
    # produces failures too, and must stay in the retry-forever
    # UpdateFailed path, not prompt the user to re-enter a perfectly
    # good token.
    aioclient_mock.get(DEVICES_URL, status=429)
    entry = _entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert not _reauth_flow_pending(hass, entry.entry_id)


async def test_a_connection_error_does_not_start_a_reauth_flow(hass, aioclient_mock):
    aioclient_mock.get(DEVICES_URL, status=500)
    entry = _entry(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert not _reauth_flow_pending(hass, entry.entry_id)
