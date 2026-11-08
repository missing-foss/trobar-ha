# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The trobar.scan_library action: the "Scan library" button's rescan, for
automations and scripts, with the server's `force` option the button
doesn't offer (re-read every file, not only those changed since the
last scan)."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import TrobarApiError
from .const import DOMAIN
from .coordinator import translated_error

SERVICE_SCAN_LIBRARY = "scan_library"
ATTR_FORCE = "force"

SCAN_LIBRARY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
    }
)


def async_setup_services(hass: HomeAssistant) -> None:
    """Registered once, at integration setup, not per entry: the action
    names its server by config entry."""

    async def _scan_library(call: ServiceCall) -> ServiceResponse:
        entry = hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="entry_not_loaded"
            )
        server = entry.runtime_data.server
        if server is None:
            # Before 2.9.0 the server has no scan action (TrobarRuntimeData).
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="scan_not_supported"
            )
        try:
            started = await server.client.async_trigger_scan(
                force=call.data[ATTR_FORCE]
            )
        except TrobarApiError as err:
            raise translated_error(err) from err
        await server.async_request_refresh()
        # False is a scan already running: the request is satisfied either way.
        return {"started": started} if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN_LIBRARY,
        _scan_library,
        schema=SCAN_LIBRARY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
