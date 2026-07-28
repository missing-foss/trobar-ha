# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for custom_components/trobar/api.py (trobar-ha#4)."""

import pytest

from custom_components.trobar.api import normalize_base_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("trobar.local", "http://trobar.local"),
        ("trobar.local/", "http://trobar.local"),
        ("http://trobar.local/", "http://trobar.local"),
        ("HTTP://Trobar.Local", "http://trobar.local"),
        ("https://trobar.example.com", "https://trobar.example.com"),
        ("  trobar.local  ", "http://trobar.local"),
        ("trobar.local:8080", "http://trobar.local:8080"),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected
