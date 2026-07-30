# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Config flow for the Trobar integration (trobar-ha#4, reauth in #28)."""

from __future__ import annotations

import logging
from collections.abc import Mapping
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

STEP_REAUTH_DATA_SCHEMA = vol.Schema({vol.Required(CONF_API_TOKEN): str})


async def _validate_token(client: TrobarApiClient) -> str | None:
    """Try the token against the server; returns an error key on failure,
    None on success. Shared between async_step_user and
    async_step_reauth_confirm (trobar-ha#28) -- same five outcomes and the
    same error-key mapping either way, only what happens on success
    (create vs. update-and-reload) differs per caller."""
    try:
        await client.async_get_devices()
    except TrobarAuthError:
        return "invalid_auth"
    except TrobarServerTooOldError:
        return "server_too_old"
    except TrobarRateLimitedError:
        return "rate_limited"
    except TrobarConnectionError:
        return "cannot_connect"
    except Exception:
        _LOGGER.exception("Unexpected error validating Trobar credentials")
        return "unknown"
    return None


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
            error = await _validate_token(client)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=base_url,
                    data={CONF_URL: base_url, CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Entry point HA calls when the coordinator raises
        ConfigEntryAuthFailed for this entry (trobar-ha#28) -- reachable
        in practice once trobar-server#478 started revoking non-admin-
        minted tokens on upgrade. Only the token step is shown next;
        nothing to collect here."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Prompt for a replacement token only -- the URL doesn't change,
        and isn't even editable here, so a token that doesn't belong to
        THIS server's URL is simply rejected by _validate_token the same
        way any other wrong token would be. That's what keeps this from
        being able to silently rebind the entry to a different Trobar
        instance (trobar-ha#28's point 3): there is no field through
        which a different URL could ever enter this flow."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()

        if user_input is not None:
            token = user_input[CONF_API_TOKEN].strip()
            client = TrobarApiClient(
                async_get_clientsession(self.hass), reauth_entry.data[CONF_URL], token
            )
            error = await _validate_token(client)
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_API_TOKEN: token},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={"url": reauth_entry.data[CONF_URL]},
        )
