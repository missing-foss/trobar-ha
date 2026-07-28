# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for the Trobar integration (trobar-ha#4).

An (empty otherwise) package marker: without it, pytest's rootdir
detection inserts tests/ itself onto sys.path rather than the repo root,
and `import custom_components.trobar...` fails to resolve.
"""
