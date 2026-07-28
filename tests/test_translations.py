# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Guard against strings.json / translations/*.json key drift (trobar-ha#9).

HA's own tooling doesn't cover this for custom integrations -- there's no
gettext/.po pipeline here (unlike the rest of the project) and no Lokalise
run to regenerate translations/*.json from strings.json, so nothing
currently stops fr.json drifting as keys are added elsewhere (#5's
sensors already grew the key set once). This is the HA-shaped equivalent
of trobar-server's dev/check_translations.py.
"""

import json
from pathlib import Path

TROBAR_DIR = Path(__file__).parent.parent / "custom_components" / "trobar"
TRANSLATION_FILES = ("strings.json", "translations/en.json", "translations/fr.json")


def _load(name: str) -> dict:
    return json.loads((TROBAR_DIR / name).read_text(encoding="utf-8"))


def _key_paths(data: dict, prefix: str = "") -> set[str]:
    """Flatten nested dict keys into dotted paths, stopping at leaf values."""
    paths: set[str] = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths |= _key_paths(value, full_key)
        else:
            paths.add(full_key)
    return paths


def test_translations_have_identical_key_sets() -> None:
    """strings.json is the source; every translation must cover exactly
    the same keys -- no more, no fewer."""
    strings_keys = _key_paths(_load("strings.json"))

    for name in ("translations/en.json", "translations/fr.json"):
        keys = _key_paths(_load(name))
        missing = strings_keys - keys
        extra = keys - strings_keys
        assert not missing and not extra, (
            f"{name} drifted from strings.json -- missing={missing} extra={extra}"
        )


def test_translation_values_are_non_empty_strings() -> None:
    """A key present but blank would pass the key-set check above and
    still ship a silently empty label or error message."""
    for name in TRANSLATION_FILES:
        data = _load(name)
        for path in _key_paths(data):
            node = data
            for part in path.split("."):
                node = node[part]
            assert isinstance(node, str) and node.strip(), f"{name}: {path!r} is empty"
