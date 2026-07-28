# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Trobar integration.

Phase A scaffolding only (trobar-ha#1): no config flow, no coordinator, no
entities yet — those land in follow-up PRs once the integration API's
payload shape is nailed down (trobar-server#446, trobar-ha#2). This module
exists so hassfest and Home Assistant's component loader have something
valid to find under `custom_components/trobar/`; it does not yet register
anything with Home Assistant.
"""
