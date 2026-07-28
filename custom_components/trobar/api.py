# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Async client for GET /api/integrations/devices (trobar-ha#4).

Talks to exactly one endpoint, added by trobar-server#446. See trobar-ha#2
for a real (redacted) response and the null-handling notes that follow
from it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp

DEVICES_PATH = "/api/integrations/devices"

# The server's own rate limit on this endpoint is its own bucket (30
# failures / 5 min -- see _authenticated_api_token in trobar-server),
# separate from the login limiter. A short client-side timeout just keeps
# a slow/unreachable server from blocking the config flow indefinitely;
# the sync data this token exposes is deliberately not time-sensitive
# (see trobar-ha#5's polling-interval reasoning), so nothing here needs to
# be generous.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)


class TrobarApiError(Exception):
    """Base class for all errors talking to a Trobar server."""


class TrobarAuthError(TrobarApiError):
    """401: the token is wrong, or was revoked since it was pasted in."""


class TrobarServerTooOldError(TrobarApiError):
    """404: /api/integrations/devices didn't exist before server 2.8.0."""


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


class TrobarApiClient:
    """Thin wrapper around GET /api/integrations/devices.

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

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Fetch the device list.

        Raises one of the TrobarApiError subclasses above on failure --
        never a bare aiohttp exception, so callers (the config flow now,
        the coordinator in trobar-ha#5) have one error surface to map.
        """
        url = f"{self._base_url}{DEVICES_PATH}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.get(
                url, headers=headers, timeout=REQUEST_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    raise TrobarAuthError
                if resp.status == 404:
                    raise TrobarServerTooOldError
                if resp.status == 429:
                    raise TrobarRateLimitedError
                resp.raise_for_status()
                return await resp.json()
        except TrobarApiError:
            raise
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TrobarConnectionError from err
