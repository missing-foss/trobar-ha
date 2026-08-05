# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Assert the resolved Home Assistant core is one we actually support.

Two properties, both about the core that *actually got installed* rather
than about the pin that asked for it:

- it is not a prerelease. pytest-homeassistant-custom-component pins an
  exact ``homeassistant==`` and cuts a release per HA beta, so an ordinary
  bump of a test dependency can silently move us onto a beta core where a
  core regression reads as our bug (trobar-ha#35, #40).
- it is at or above the minimum ``hacs.json`` advertises. This is the one
  that would have caught trobar-ha#38: for months the suite ran against
  2026.2.2 while we declared 2026.3.0, so the tests could not exercise any
  version we claimed to support.

Nothing in pytest-HA's own version number states which core it carries,
which is why both checks assert on the installed distribution.

Run from anywhere; paths resolve relative to this file, not the cwd.
"""

from __future__ import annotations

import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.version import Version

HACS_JSON = Path(__file__).resolve().parent.parent / "hacs.json"


def fail(message: str) -> None:
    # GitHub renders ::error:: as an annotation on the job; a plain line is
    # what dev/verify.sh wants. Same script either way.
    prefix = "::error::" if os.environ.get("GITHUB_ACTIONS") else "CORE: "
    print(f"{prefix}{message}")


def main() -> int:
    try:
        core = Version(version("homeassistant"))
    except PackageNotFoundError:
        fail("homeassistant is not installed — cannot check the resolved core")
        return 1

    declared = Version(json.loads(HACS_JSON.read_text())["homeassistant"])

    if core.is_prerelease:
        fail(
            f"resolved homeassistant {core} is a prerelease; "
            f"we do not support HA betas"
        )
        return 1

    if core < declared:
        fail(
            f"resolved homeassistant {core} is BELOW the {declared} minimum "
            f"declared in hacs.json — the suite cannot exercise a version we "
            f"claim to support"
        )
        return 1

    print(f"homeassistant {core} (stable, >= hacs.json minimum {declared})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
