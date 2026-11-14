# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""DataUpdateCoordinators for Trobar (trobar-ha#5, server metrics in
#25, mirror health).

Three coordinators, deliberately separate rather than one that fetches
every route per cycle: GET /api/integrations/devices,
GET /api/integrations/server and GET /api/integrations/mirrors are
independent failure domains (#25's own "reachable" signal has to stay
meaningful even if, say, the server route alone hiccups), and combining
them would flip every per-device entity unavailable over a failure that
has nothing to do with any device.

Mirrors adds a wrinkle the other two don't have: its server floor is
2.12.0, four minors above the rest, so on an older server that one route
404s while everything else works. See TrobarMirrorsDataUpdateCoordinator.
GET /api/integrations/playlist-sources, newer still, is a fourth with the
same wrinkle: TrobarPlaylistSourcesDataUpdateCoordinator.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TrobarApiClient,
    TrobarApiError,
    TrobarAuthError,
    TrobarConnectionError,
    TrobarRateLimitedError,
    TrobarServerTooOldError,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES, DOMAIN

_ERROR_MESSAGES: dict[type[TrobarApiError], str] = {
    TrobarAuthError: "Token was rejected -- it may have been revoked",
    TrobarServerTooOldError: "Server too old for the integration API (need 2.8.0+)",
    TrobarRateLimitedError: "Rate-limited by the server; will retry next interval",
    TrobarConnectionError: "Could not reach the server",
}

# The same failures, as translation keys under "exceptions", for errors
# shown to a person: a button press or a service call.
_ERROR_TRANSLATION_KEYS: dict[type[TrobarApiError], str] = {
    TrobarAuthError: "token_rejected",
    TrobarServerTooOldError: "server_too_old",
    TrobarRateLimitedError: "rate_limited",
    TrobarConnectionError: "cannot_connect",
}


def translated_error(err: TrobarApiError) -> HomeAssistantError:
    """A HomeAssistantError that HA shows in the person's language; an error
    type with no key of its own falls back to one naming the error."""
    key = _ERROR_TRANSLATION_KEYS.get(type(err))
    if key is None:
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="request_failed",
            translation_placeholders={"error": str(err) or type(err).__name__},
        )
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)


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
#
# The 5 minutes is the default; the options flow sets the interval per
# config entry (1 to 60 minutes) and a change reloads the entry.
def update_interval(entry: ConfigEntry) -> timedelta:
    return timedelta(
        minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MINUTES)
    )


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
            update_interval=update_interval(entry),
            # Listeners (entity state writes, the device add/remove sync)
            # run only when a poll returns something different.
            always_update=False,
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

    `supported` works as the mirrors coordinator's does, for the same
    reason: this route arrived in 2.9.0, and 2.8.1 is a supported floor
    for the per-device sensors alone, so a 404 here skips the server
    entities rather than failing (and endlessly retrying) the whole entry.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar server",
            update_interval=update_interval(entry),
            # Listeners (entity state writes, the device add/remove sync)
            # run only when a poll returns something different.
            always_update=False,
        )
        self.client = client
        self.supported = True

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_server_status()
        except TrobarServerTooOldError as err:
            self.supported = False
            raise UpdateFailed(
                "Server route answered 404 (needs server 2.9.0+, or the "
                "route isn't reachable)"
            ) from err
        except TrobarApiError as err:
            _raise_for_api_error(err)
            raise AssertionError("unreachable")  # pragma: no cover


class TrobarMirrorsDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch instance-wide playlist-mirror health (trobar-ha#32,
    trobar-server#506). A third coordinator for the same reason there are
    already two: GET /api/integrations/mirrors is its own failure domain,
    and a mirrors hiccup must not take the reachability signal or the
    per-device entities down with it.

    `supported` exists because this route's server floor is 2.12.0 while
    the integration as a whole supports 2.8.0+. A 404 here therefore means
    "this server predates mirrors", NOT "this server is too old for
    Trobar" -- so it is recorded rather than merely raised, letting
    __init__.py skip the mirror entities on an older server instead of
    shipping two entities that can only ever read unavailable. It starts
    True and only ever goes False: an unreachable server at startup must
    not be mistaken for an old one, since that would silently drop the
    entities until the next reload.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar mirrors",
            update_interval=update_interval(entry),
            # Listeners (entity state writes, the device add/remove sync)
            # run only when a poll returns something different.
            always_update=False,
        )
        self._client = client
        self.supported = True

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._client.async_get_mirrors()
        except TrobarServerTooOldError as err:
            self.supported = False
            # Same care as __init__.py's log line: state the observation,
            # not a diagnosis. A 404 here is "route absent", which is
            # usually an old server and sometimes a proxy that doesn't
            # forward this path.
            raise UpdateFailed(
                "Mirrors route answered 404 (needs server 2.12.0+, or the "
                "route isn't reachable)"
            ) from err
        except TrobarApiError as err:
            _raise_for_api_error(err)
            raise AssertionError("unreachable")  # pragma: no cover


class TrobarPlaylistSourcesDataUpdateCoordinator(
    DataUpdateCoordinator[dict[str, Any]]
):
    """Fetch playlist-source health: the library source, members' own
    listings, linked streaming accounts and public links that a playlist
    sync reads from. Its own coordinator, for the reason mirrors has one:
    a failure here must not take the other entities down.

    `supported` works exactly as TrobarMirrorsDataUpdateCoordinator's
    does: the route is newer than every other one, so a 404 means "this
    server predates playlist-source health" (or a proxy doesn't forward
    the path), and __init__.py skips the two entities. It starts True and
    only a 404 sets it False.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar playlist sources",
            update_interval=update_interval(entry),
            always_update=False,
        )
        self._client = client
        self.supported = True

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._client.async_get_playlist_sources()
        except TrobarServerTooOldError as err:
            self.supported = False
            raise UpdateFailed(
                "Playlist sources route answered 404 (needs a server with "
                "playlist-source health, or the route isn't reachable)"
            ) from err
        except TrobarApiError as err:
            _raise_for_api_error(err)
            raise AssertionError("unreachable")  # pragma: no cover


class TrobarPlaylistsDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch each device's playlists and the server's playlist totals
    (trobar-ha#19). Its own coordinator, as mirrors and playlist sources
    have one: a failure here must not take the other entities down.

    `supported` works as theirs does: the route is newer than the others,
    so a 404 means the server predates it (or a proxy doesn't forward the
    path), and __init__.py skips the playlist entities and the sync
    button. It starts True and only a 404 sets it False.
    """

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: TrobarApiClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Trobar playlists",
            update_interval=update_interval(entry),
            always_update=False,
        )
        self.client = client
        self.supported = True

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_playlists()
        except TrobarServerTooOldError as err:
            self.supported = False
            raise UpdateFailed(
                "Playlists route answered 404 (needs a server with playlist "
                "entities, or the route isn't reachable)"
            ) from err
        except TrobarApiError as err:
            _raise_for_api_error(err)
            raise AssertionError("unreachable")  # pragma: no cover
