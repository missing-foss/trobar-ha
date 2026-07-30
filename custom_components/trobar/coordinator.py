# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DataUpdateCoordinators for Trobar (trobar-ha#5, server metrics in #25).

Two coordinators, deliberately separate rather than one that fetches
both routes per cycle: GET /api/integrations/devices and
GET /api/integrations/server are independent failure domains (#25's own
"reachable" signal has to stay meaningful even if, say, the server route
alone hiccups), and combining them would flip every per-device entity
unavailable over a failure that has nothing to do with any device.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TrobarApiClient,
    TrobarApiError,
    TrobarAuthError,
    TrobarConnectionError,
    TrobarRateLimitedError,
    TrobarServerTooOldError,
)

_ERROR_MESSAGES: dict[type[TrobarApiError], str] = {
    TrobarAuthError: "Token was rejected -- it may have been revoked",
    TrobarServerTooOldError: "Server too old for the integration API (need 2.8.0+)",
    TrobarRateLimitedError: "Rate-limited by the server; will retry next interval",
    TrobarConnectionError: "Could not reach the server",
}

_LOGGER = logging.getLogger(__name__)

# Every request bumps last_used_at server-side and counts against the
# token's own rate-limit bucket (30 failures / 5 min -- see api.py). Sync
# itself is a slow-moving thing: the Android client syncs on a 6-hour
# period, so polling every 30 seconds would fetch an identical payload
# hundreds of times between real changes. A few minutes is frequent
# enough that a dashboard feels current without paying for polling that
# fine-grained.
#
# The server coordinator below reuses this same interval rather than the
# slower cadence trobar-ha#25 floated as worth considering: that
# suggestion predated trobar-server#475 actually landing, and #475's own
# route measured its query at ~2ms against a 59,000-track library --
# cheap enough that matching the device poll (and getting "scan running"
# /  "reachable" at the same freshness as everything else) costs nothing
# worth trading away.
UPDATE_INTERVAL = timedelta(minutes=5)


def _raise_for_api_error(err: TrobarApiError) -> None:
    """Shared by both coordinators below: TrobarAuthError becomes
    ConfigEntryAuthFailed (trobar-ha#28 -- starts the entry's reauth flow
    instead of retrying a token that can never start working again by
    itself), everything else becomes the generic UpdateFailed. Always
    raises; never returns."""
    if isinstance(err, TrobarAuthError):
        raise ConfigEntryAuthFailed(_ERROR_MESSAGES[TrobarAuthError]) from err
    message = _ERROR_MESSAGES.get(type(err), str(err) or type(err).__name__)
    raise UpdateFailed(message) from err


class TrobarDataUpdateCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Fetch the device list once per interval, keyed by Trobar device id."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar",
            update_interval=UPDATE_INTERVAL,
        )
        self._client = client

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        """Fetch and re-key by device id.

        A failure here (rate limit, server too old, connection) becomes
        UpdateFailed, which the coordinator turns into every entity going
        unavailable as a whole. That's the right behaviour for "the poll
        itself failed" (trobar-ha#5); a single device vanishing from an
        otherwise-successful response is a different case, handled in
        sensor.py by comparing device-id sets between refreshes, not here.
        Auth is handled separately -- see _raise_for_api_error.
        """
        try:
            devices = await self._client.async_get_devices()
        except TrobarApiError as err:
            _raise_for_api_error(err)
        return {device["id"]: device for device in devices}


class TrobarServerDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch instance-wide server metrics once per interval (trobar-ha#25,
    trobar-server#475). A flat dict, not keyed by anything -- unlike the
    device coordinator, there's only ever one "row" here.

    `client` is public here (unlike the device coordinator's private
    one) because button.py needs it too, for the same admin-minted token
    -- POST /api/integrations/actions/scan is a write, not a poll, so it
    doesn't belong inside _async_update_data, but the button still wants
    this coordinator's device-linkage and availability, not a client of
    its own to keep in sync.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar server",
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_server_status()
        except TrobarApiError as err:
            _raise_for_api_error(err)
            raise AssertionError("unreachable")  # pragma: no cover
