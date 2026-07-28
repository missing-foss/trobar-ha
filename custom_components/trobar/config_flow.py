# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Config flow for the Trobar integration (trobar-ha#4)."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    TrobarApiClient,
    TrobarAuthError,
    TrobarConnectionError,
    TrobarRateLimitedError,
    TrobarServerTooOldError,
    normalize_base_url,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Required(CONF_API_TOKEN): str,
    }
)


class TrobarConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Trobar.

    One entry per Trobar server -- manifest.json declares
    integration_type "hub", and devices become HA devices beneath it in
    the follow-up (trobar-ha#5), not one entry per device.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial (and only) step: URL + token, validated live
        against the server before the entry is created."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = normalize_base_url(user_input[CONF_URL])
            token = user_input[CONF_API_TOKEN].strip()

            # Cheap duplicate check before the network round-trip: a
            # second entry for a server that's already configured should
            # abort here, not after spending the user's one attempt in
            # this token's 5-minute rate-limit window.
            await self.async_set_unique_id(base_url)
            self._abort_if_unique_id_configured()

            client = TrobarApiClient(
                async_get_clientsession(self.hass), base_url, token
            )
            try:
                await client.async_get_devices()
            except TrobarAuthError:
                errors["base"] = "invalid_auth"
            except TrobarServerTooOldError:
                errors["base"] = "server_too_old"
            except TrobarRateLimitedError:
                errors["base"] = "rate_limited"
            except TrobarConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Trobar credentials")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=base_url,
                    data={CONF_URL: base_url, CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )
