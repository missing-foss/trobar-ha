# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for custom_components/trobar/api.py (trobar-ha#4, trobar-ha#5)."""

from datetime import UTC, datetime

import pytest

from custom_components.trobar.api import (
    has_url_scheme,
    normalize_base_url,
    parse_server_timestamp,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://trobar.local", True),
        ("https://trobar.local", True),
        ("  HTTPS://Trobar.Local", True),
        ("trobar.local", False),
        ("ftp://trobar.local", False),
        ("httpx://trobar.local", False),
    ],
)
def test_has_url_scheme(raw: str, expected: bool) -> None:
    assert has_url_scheme(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://trobar.local", "http://trobar.local"),
        ("https://trobar.local/", "https://trobar.local"),
        ("http://trobar.local/", "http://trobar.local"),
        ("HTTP://Trobar.Local", "http://trobar.local"),
        ("https://trobar.example.com", "https://trobar.example.com"),
        ("  http://trobar.local  ", "http://trobar.local"),
        ("http://trobar.local:8080", "http://trobar.local:8080"),
        ("trobar.local", "trobar.local"),  # never adds a scheme
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


def test_parse_server_timestamp_none_is_none() -> None:
    # sync_status.last_synced_at for a never-synced device (trobar-ha#2).
    assert parse_server_timestamp(None) is None


def test_parse_server_timestamp_parses_sqlite_datetime_as_utc() -> None:
    # SQLite's datetime('now') form: space-separated, no offset, but the
    # server always writes it in UTC.
    result = parse_server_timestamp("2026-07-28 21:58:19")
    assert result == datetime(2026, 7, 28, 21, 58, 19, tzinfo=UTC)


def test_parse_server_timestamp_keeps_an_offset_the_value_carries() -> None:
    # Only a naive value is UTC by convention; one with an offset already
    # names its instant, and replacing the offset would move it.
    result = parse_server_timestamp("2026-07-28T23:58:19+02:00")
    assert result == datetime(2026, 7, 28, 21, 58, 19, tzinfo=UTC)
