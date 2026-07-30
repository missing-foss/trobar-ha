# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async client for the /api/integrations/* routes (trobar-ha#4, #25).

Devices (trobar-server#446) shipped first; server-wide metrics and the
rescan action (trobar-server#474/#475, server 2.9.0) share the same
admin-minted token and the same three error statuses, so
_request_json() below is the one place that maps them -- see trobar-ha#2
for a real (redacted) devices response and the null-handling notes that
follow from it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

DEVICES_PATH = "/api/integrations/devices"
SERVER_PATH = "/api/integrations/server"
ACTIONS_SCAN_PATH = "/api/integrations/actions/scan"

# The server's own rate limit on these routes is its own bucket (30
# failures / 5 min, shared across all three as of trobar-server#474 --
# see _authenticated_integration_token in trobar-server), separate from
# the login limiter. A short client-side timeout just keeps a slow/
# unreachable server from blocking the config flow indefinitely; the
# sync data this token exposes is deliberately not time-sensitive (see
# trobar-ha#5's polling-interval reasoning), so nothing here needs to be
# generous.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class TrobarApiError(Exception):
    """Base class for all errors talking to a Trobar server."""


class TrobarAuthError(TrobarApiError):
    """401: the token is wrong, or was revoked since it was pasted in."""


class TrobarServerTooOldError(TrobarApiError):
    """404: this route doesn't exist on the target server -- it predates
    whichever trobar-server version added it (2.8.0 for devices, 2.9.0
    for server metrics and the rescan action)."""


class TrobarRateLimitedError(TrobarApiError):
    """429: the integration's own rate-limit bucket, not the login one."""


class TrobarConnectionError(TrobarApiError):
    """Network-level failure: wrong URL, server down, TLS, timeout -- and
    also any other non-2xx status. The issue's error mapping only asks
    for 401/404/429 to be distinguished; a 5xx is close enough to
    "couldn't reach it" from the user's side that a fourth bucket isn't
    worth the extra UI copy."""


def normalize_base_url(raw: str) -> str:
    """Canonicalise a user-pasted server URL.

    Used both as the outgoing request base and as the config entry's
    unique ID -- the payload carries no server-side instance id (see
    trobar-ha#4), so two entries typed slightly differently but pointing
    at the same server must still collapse to one. Decided once, here:
    default to "http://" when no scheme is given (self-hosted Trobar
    instances are typically LAN-only and plain), lower-case the scheme
    and host, and drop a trailing slash.
    """
    raw = raw.strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def parse_server_timestamp(raw: str | None) -> datetime | None:
    """Parse a trobar-server timestamp column into an aware datetime.

    The server stores these with SQLite's `datetime('now')` (trobar-ha#5),
    which yields "YYYY-MM-DD HH:MM:SS" -- UTC, but with no "T" separator
    and no offset, so it is not quite ISO 8601. `datetime.fromisoformat`
    accepts the space-separated form directly (Python 3.11+); the UTC
    offset still has to be attached by hand, since the string itself
    doesn't carry one.
    """
    if raw is None:
        return None
    return datetime.fromisoformat(raw).replace(tzinfo=UTC)


class TrobarApiClient:
    """Thin wrapper around the /api/integrations/* routes.

    Takes Home Assistant's shared aiohttp session rather than creating its
    own -- the standard for custom integrations, and it avoids leaking a
    session per config entry.
    """

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, token: str
    ) -> None:
        self._session = session
        self._base_url = base_url
        self._token = token

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        extra_ok_statuses: frozenset[int] = frozenset(),
    ) -> tuple[int, Any]:
        """One request, one place that maps the shared 401/404/429
        statuses to their exceptions -- never a bare aiohttp exception,
        so callers (the config flow, both coordinators, the button) have
        one error surface to handle. Returns (status, parsed_json) rather
        than raising on every non-2xx: extra_ok_statuses lets a caller
        accept a status that would otherwise hit raise_for_status(),
        used by the actions/scan route's 409 ("already running" -- a
        normal outcome for that caller, not an error)."""
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.request(
                method, url, headers=headers, json=json, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise TrobarAuthError
                if resp.status == 404:
                    raise TrobarServerTooOldError
                if resp.status == 429:
                    raise TrobarRateLimitedError
                if resp.status not in extra_ok_statuses:
                    resp.raise_for_status()
                return resp.status, await resp.json()
        except TrobarApiError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TrobarConnectionError from err

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Fetch the device list (trobar-server#446)."""
        _, body = await self._request_json("GET", DEVICES_PATH)
        return body

    async def async_get_server_status(self) -> dict[str, Any]:
        """Fetch instance-wide metrics: version, track count, library
        size, scan status (trobar-server#475, server 2.9.0)."""
        _, body = await self._request_json("GET", SERVER_PATH)
        return body

    async def async_trigger_scan(self, *, force: bool = False) -> bool:
        """Trigger a library rescan (trobar-server#474, server 2.9.0).

        Returns True if this call started a new scan, False if one was
        already running (409). Both satisfy the caller's actual intent
        -- "make sure a scan happens" -- so 409 is a normal outcome here,
        not an error a button press should surface as one.
        """
        status, _ = await self._request_json(
            "POST", ACTIONS_SCAN_PATH, json={"force": force}, extra_ok_statuses={409}
        )
        return status != 409
