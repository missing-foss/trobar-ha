<!--
SPDX-FileCopyrightText: 2026 missing-foss

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing

This is the Home Assistant client of Trobar — the contribution guidelines,
issue tracker conventions, and dev-environment notes live in the main server
repository's `CONTRIBUTING.md` and `docs/`. Short version: open an issue
before large PRs, `dev/verify.sh` must pass, contributions are
`GPL-3.0-or-later` like the integration itself.

Public issues and PRs live here on GitHub.

Contributing a translation? See [Translating Trobar](https://missing-foss.github.io/trobar-server/project/translations/).

## Local setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
dev/verify.sh
```

`dev/verify.sh` covers everything CI's `validate` job checks (lint,
tests, the household leak scan, gitleaks, REUSE). It does **not** run
`hassfest` — that needs Docker and only runs in CI; see
`.github/workflows/ci.yml`.

## Status

Working: config flow, coordinator, and sensor entities are all in place
(see the [README](README.md#status) for what that covers). What's left is
Phase B of [trobar-ha#1](https://github.com/missing-foss/trobar-ha/issues/1)
— device triggers, notifications, a default-store HACS listing — deferred
until the integration has seen some real use. See
[trobar-server#270](https://github.com/missing-foss/trobar-server/issues/270)
for the integration's design and why a `media_player` model was rejected —
this is a monitoring/automation surface over the sync lifecycle, not a
renderer.

Security issues: not in the public tracker — missing_foss@etik.com.
