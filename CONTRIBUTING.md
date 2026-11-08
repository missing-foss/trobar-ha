<!--
SPDX-FileCopyrightText: 2026 missing-foss

SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contributing

This is the Home Assistant client of Trobar — the contribution guidelines,
issue tracker conventions, and dev-environment notes live in the main server
repository's `CONTRIBUTING.md` and `docs/`. Short version: open an issue
before large PRs, AI-assisted patches are fine if you say so in the PR,
`dev/verify.sh` must pass, contributions are `GPL-3.0-or-later` like the
integration itself.

Public issues and PRs live here on GitHub.

Pull requests opened here are reviewed and then shipped by the maintainers
rather than merged in place, so your commits may arrive under a release
commit rather than your own. Your pull request is closed with a note
crediting you when the change lands. Keep changes focused — a small pull
request with a clear rationale is much easier to take than a large one.

Contributing a translation? See [Translating Trobar](https://missing-foss.github.io/trobar-server/project/translations/).

## Local setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
dev/verify.sh
```

`dev/verify.sh` covers everything CI's `validate` job checks (lint,
tests, gitleaks, REUSE). It does **not** run `hassfest` — that needs
Docker and only runs in CI; see `.github/workflows/ci.yml`.

## Status

Working: config flow, coordinator, and sensor entities are all in place
(see the [README](README.md#status) for what that covers). What's left is
a second phase — device triggers, notifications, a default-store HACS
listing — deferred until the integration has seen some real use.

The integration is deliberately a monitoring and automation surface over the
sync lifecycle rather than a renderer, which is why it does not use the
`media_player` model.

Security issues: not in the public tracker — missing_foss@etik.com.
