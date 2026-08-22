# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tests for custom_components/trobar/api.py (trobar-ha#4, trobar-ha#5)."""

from datetime import UTC, datetime

import pytest

from custom_components.trobar.api import normalize_base_url, parse_server_timestamp


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


def test_parse_server_timestamp_none_is_none() -> None:
    # sync_status.last_synced_at for a never-synced device (trobar-ha#2).
    assert parse_server_timestamp(None) is None


def test_parse_server_timestamp_parses_sqlite_datetime_as_utc() -> None:
    # SQLite's datetime('now') form: space-separated, no offset, but the
    # server always writes it in UTC.
    result = parse_server_timestamp("2026-07-28 21:58:19")
    assert result == datetime(2026, 7, 28, 21, 58, 19, tzinfo=UTC)
