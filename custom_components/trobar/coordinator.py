# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DataUpdateCoordinator for Trobar (trobar-ha#5).

One GET /api/integrations/devices per refresh, shared by every entity --
never one request per sensor.
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
UPDATE_INTERVAL = timedelta(minutes=5)


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

        Auth is the odd one out (trobar-ha#28): retrying a revoked or
        wrong token can never succeed, so it must not fall into the same
        UpdateFailed bucket as a transient failure. Raising
        ConfigEntryAuthFailed here is what makes the coordinator (it was
        constructed with config_entry=entry) start the config entry's
        reauth flow instead of retrying forever -- this became reachable
        in practice once trobar-server#478 started revoking non-admin-
        minted tokens on upgrade. Must be caught before the generic
        TrobarApiError below, since TrobarAuthError is a subclass of it.
        """
        try:
            devices = await self._client.async_get_devices()
        except TrobarAuthError as err:
            raise ConfigEntryAuthFailed(_ERROR_MESSAGES[TrobarAuthError]) from err
        except TrobarApiError as err:
            message = _ERROR_MESSAGES.get(type(err), str(err) or type(err).__name__)
            raise UpdateFailed(message) from err
        return {device["id"]: device for device in devices}
