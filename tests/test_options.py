# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The options flow's poll interval (trobar-ha#21)."""

from datetime import timedelta

import pytest
import voluptuous as vol
from homeassistant.data_entry_flow import FlowResultType

from custom_components.trobar.const import CONF_SCAN_INTERVAL

from .test_sensor import PHONE_DEVICE, _setup_entry


def _form_default(flow) -> int:
    return next(
        k.default() for k in flow["data_schema"].schema if k == CONF_SCAN_INTERVAL
    )


def _intervals(entry) -> set[timedelta]:
    runtime = entry.runtime_data
    return {
        c.update_interval for c in (runtime.devices, runtime.server, runtime.mirrors)
    }


async def test_the_default_is_five_minutes_and_listeners_skip_unchanged_polls(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    assert _intervals(entry) == {timedelta(minutes=5)}
    runtime = entry.runtime_data
    assert {
        c.always_update for c in (runtime.devices, runtime.server, runtime.mirrors)
    } == {False}


async def test_saving_the_option_reloads_every_coordinator_with_it(
    hass, aioclient_mock
):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] is FlowResultType.FORM
    # The form offers the current value.
    assert _form_default(flow) == 5

    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], user_input={CONF_SCAN_INTERVAL: 15}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 15}
    assert _intervals(entry) == {timedelta(minutes=15)}

    # Opened again, the form offers the saved value, not the default.
    again = await hass.config_entries.options.async_init(entry.entry_id)
    assert _form_default(again) == 15


@pytest.mark.parametrize("value", [0, 61])
async def test_an_interval_outside_one_to_sixty_minutes_is_refused(
    hass, aioclient_mock, value
):
    entry = await _setup_entry(hass, aioclient_mock, [PHONE_DEVICE])
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            flow["flow_id"], user_input={CONF_SCAN_INTERVAL: value}
        )
    assert entry.options == {}
