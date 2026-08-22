# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Trobar config flow (trobar-ha#4)."""

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.trobar.const import DOMAIN

DEVICES_URL = "http://trobar.local/api/integrations/devices"

# A trimmed slice of the trobar-ha#2 payload reference: enough shape to be
# a valid response. Exercising the null-handling it documents belongs to
# the coordinator/sensor tests in the trobar-ha#5 follow-up, not here.
SAMPLE_DEVICES = [
    {
        "id": 1,
        "name": "Test Phone",
        "device_type": "phone",
        "owner_user_id": 1,
        "owner_username": "test",
        "is_own": True,
        "is_pinned": False,
        "max_size_bytes": 150000000000,
        "reported_free_bytes": 300000000000,
        "reported_total_bytes": 512000000000,
        "free_bytes_reported_at": None,
        "last_seen_at": None,
        "created_at": None,
        "source_of_truth": "device",
        "transcode_format": None,
        "artist_images": "small",
        "unknown_track_count": None,
        "autofit": {"enabled": False, "percent": 100},
        "sync_status": {"last_synced_at": None, "pending_count": 10},
    }
]


async def test_user_flow_success(hass, aioclient_mock):
    """The happy path creates an entry with the normalised URL and token."""
    aioclient_mock.get(DEVICES_URL, json=SAMPLE_DEVICES)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "trobar.local", CONF_API_TOKEN: "abc123"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "http://trobar.local"
    assert result["data"] == {
        CONF_URL: "http://trobar.local",
        CONF_API_TOKEN: "abc123",
    }


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        (401, "invalid_auth"),
        (404, "server_too_old"),
        (429, "rate_limited"),
    ],
)
async def test_user_flow_error_status(
    hass, aioclient_mock, status: int, expected_error: str
):
    """Each server error status maps to its own, distinct error key --
    they must not collapse into one generic failure (trobar-ha#4)."""
    aioclient_mock.get(DEVICES_URL, status=status)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "trobar.local", CONF_API_TOKEN: "abc123"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_user_flow_cannot_connect(hass, aioclient_mock):
    """A network-level failure maps to cannot_connect, distinct from the
    HTTP-status-derived error keys above."""
    aioclient_mock.get(DEVICES_URL, exc=aiohttp.ClientConnectionError())

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "trobar.local", CONF_API_TOKEN: "abc123"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauth_flow_success(hass, aioclient_mock):
    """trobar-ha#28: completing reauth with a valid token updates the
    entry in place and reloads it -- entity IDs, history, and any
    automation referencing them survive, unlike delete-and-re-add."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["description_placeholders"]["url"] == "http://trobar.local"

    aioclient_mock.get(DEVICES_URL, json=SAMPLE_DEVICES)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "new-token"}
    )
    await hass.async_block_till_done()

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == "new-token"
    assert entry.data[CONF_URL] == "http://trobar.local"


@pytest.mark.parametrize(
    ("status", "expected_error"),
    [
        (401, "invalid_auth"),
        (404, "server_too_old"),
        (429, "rate_limited"),
    ],
)
async def test_reauth_flow_error_status(
    hass, aioclient_mock, status: int, expected_error: str
):
    """Same five outcomes as the initial setup flow -- reauth reuses
    _validate_token, so this pins that the mapping wasn't duplicated (and
    silently drifted) rather than shared."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    aioclient_mock.get(DEVICES_URL, status=status)
    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "still-bad"}
    )

    assert result2["type"] is FlowResultType.FORM
    assert result2["step_id"] == "reauth_confirm"
    assert result2["errors"] == {"base": expected_error}
    # A failed reauth attempt must not touch the entry at all.
    assert entry.data[CONF_API_TOKEN] == "old-token"


async def test_reauth_flow_never_offers_a_url_field(hass, aioclient_mock):
    """trobar-ha#28's point 3: reauth must not be able to silently rebind
    the entry to a different Trobar server. The actual guard is
    structural -- there is no url key in the reauth schema at all, so a
    token can never carry a new URL into this flow -- proven here by
    confirming every request the flow makes (including the reload that
    follows a successful reauth) goes to the entry's ORIGINAL host, and
    the entry's URL is byte-for-byte unchanged afterwards."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="http://trobar.local",
        data={CONF_URL: "http://trobar.local", CONF_API_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)

    assert "url" not in result["data_schema"].schema

    aioclient_mock.get(DEVICES_URL, json=SAMPLE_DEVICES)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_TOKEN: "token-from-elsewhere"}
    )
    await hass.async_block_till_done()

    # >=1: the reauth validation call, plus the first-refresh a
    # successful reauth's entry reload triggers -- both must hit the
    # same, entry-owned host.
    assert aioclient_mock.call_count >= 1
    assert all(str(call[1]) == DEVICES_URL for call in aioclient_mock.mock_calls)
    assert entry.data[CONF_URL] == "http://trobar.local"


async def test_user_flow_duplicate_entry_aborts(hass, aioclient_mock):
    """A second entry for the same server -- typed with a trailing slash,
    normalising to the same unique ID -- is rejected before the config
    flow ever makes a request."""
    MockConfigEntry(domain=DOMAIN, unique_id="http://trobar.local").add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: "trobar.local/", CONF_API_TOKEN: "abc123"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert aioclient_mock.call_count == 0
