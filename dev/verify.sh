#!/usr/bin/env bash

# SPDX-FileCopyrightText: 2026 missing-foss
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Pre-push verification gate for trobar-ha. Run from the repo root:
#   dev/verify.sh
# CI (.github/workflows/ci.yml) runs the same checks, plus hassfest (Home
# Assistant's own manifest/integration validator, which needs Docker and
# isn't practical to run locally here — see ci.yml).
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
fail=0
step() { echo; echo "== $1 =="; }

step "lint (ruff)"
if command -v ruff >/dev/null 2>&1; then
  ruff check . && echo ok || fail=1
else
  echo "SKIP (ruff not installed — pip install -r requirements-dev.txt) — CI still runs it"
fi

step "leak scan (household infra must never ship)"
# #404: `grep -f` on a missing terms file exits 2 (swallowed by 2>/dev/null
# below), the `if` is then false, and this printed "ok" having scanned
# nothing — fail-open, not fail-safe. `-s` catches missing AND empty in one
# test, skipping the grep entirely so this doesn't ALSO scan (and pass)
# against a pattern file with nothing in it.
if [ ! -s dev/forbidden-terms.txt ]; then
  echo "LEAK: dev/forbidden-terms.txt missing or empty — scan did not run"; fail=1
elif git ls-files | xargs grep -InE -f dev/forbidden-terms.txt 2>/dev/null \
     | grep -viE "^[^:]*\.lock:|^dev/forbidden-terms\.txt:"; then
  echo "LEAK: forbidden term(s) above"; fail=1
else
  echo "ok"
fi

step "gitleaks (secrets)"
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks git --no-banner . && echo ok || fail=1
else
  echo "SKIP (gitleaks not installed) — CI still runs it"
fi

step "REUSE (per-file SPDX licensing)"
if command -v reuse >/dev/null 2>&1; then
  if reuse lint >/dev/null 2>&1; then echo ok; else reuse lint | tail -20; fail=1; fi
else
  echo "SKIP (reuse not installed — pipx install reuse) — CI still runs it"
fi

echo
if [ "$fail" -eq 0 ]; then echo "VERIFY OK"; else echo "VERIFY FAILED"; fi
exit "$fail"
