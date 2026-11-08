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

step "resolved HA core is supported"
# Not a prerelease, and at or above hacs.json's declared minimum. See
# dev/check_core.py for why both properties are asserted on the INSTALLED
# distribution rather than on the pin. CI runs this twice — once per core
# it tests (#38); locally it checks whatever venv you're in.
if python3 -c "import homeassistant" >/dev/null 2>&1; then
  if python3 dev/check_core.py; then echo ok; else fail=1; fi
else
  echo "SKIP (homeassistant not installed — pip install -r requirements-dev.txt) — CI still runs it"
fi

step "lint (ruff)"
if command -v ruff >/dev/null 2>&1; then
  ruff check . && echo ok || fail=1
else
  echo "FAIL: ruff is not installed (pip install -r requirements-dev.txt) — the lint cannot run"; fail=1
fi

step "tests (pytest)"
# Checked via the plugin import, not just `command -v pytest`: a `pytest`
# binary from an unrelated project's venv earlier on PATH would otherwise
# look "installed" here and then fail on the missing HA test harness.
if python3 -c "import pytest_homeassistant_custom_component" >/dev/null 2>&1; then
  pytest && echo ok || fail=1
else
  echo "SKIP (pytest-homeassistant-custom-component not installed — pip install -r requirements-dev.txt) — CI still runs it"
fi

step "leak scan (strings that must never ship)"
# #404: `grep -f` on a missing terms file exits 2 (swallowed by 2>/dev/null
# below), the `if` is then false, and this printed "ok" having scanned
# nothing — fail-open, not fail-safe. `-s` catches missing AND empty in one
# test, skipping the grep entirely so this doesn't ALSO scan (and pass)
# against a pattern file with nothing in it.
# The pattern list is NOT in this repository. A denylist that ships the terms
# it exists to exclude publishes exactly what it is protecting -- which is what
# used to happen here. Supply one via LEAK_PATTERNS to run it; with no
# list configured this reports that it did not run rather than passing.
# A `-f` list has no comment syntax and no blank-line syntax: grep takes every
# line in the file as a pattern, including the ones a human wrote as structure.
# So anything not meant as a pattern is stripped before grep sees the list. If
# stripping leaves nothing the list is malformed, and that fails loudly rather
# than scanning against an empty pattern set and reporting "ok". The count is
# printed on success so a list that quietly shrinks is visible.
# The filtered list is fed to grep through process substitution and never
# written to disk. A 0600 file removed on EXIT is still a copy of a list whose
# one handling rule is that it is not copied, and EXIT does not run on SIGKILL,
# on a full disk, or when a CI container is torn down mid-step. This removes
# the cleanup path rather than managing it.
# ONE grep invocation, deliberately. `git ls-files | xargs grep` may run grep
# several times: a temp file is re-opened by each, but a process substitution
# is a pipe and is drained by the first, so later batches would scan against an
# empty pattern set and report clean -- no error, no change in exit status. The
# file list is passed as arguments instead, in an array so paths containing
# spaces survive. Should that list ever outgrow ARG_MAX, this fails loudly with
# E2BIG rather than quietly under-scanning.
if [ -n "${LEAK_PATTERNS:-}" ] && [ -s "${LEAK_PATTERNS}" ]; then
  mapfile -t leak_files < <(git ls-files)
  leak_n=$(grep -vcE '^[[:space:]]*(#|$)' "${LEAK_PATTERNS}")
  if [ "${#leak_files[@]}" -eq 0 ]; then
    # grep with no file operands reads stdin: it would hang rather than scan,
    # and a scan of zero files reporting "ok" would be vacuous either way.
    echo "FAIL: no tracked files to scan"; fail=1
  elif [ "${leak_n:-0}" -eq 0 ]; then
    echo "FAIL: pattern list has no usable patterns (comments and blanks only)"; fail=1
  else
    # grep exits 0 on match, 1 on no match, and 2 on error. An `if` reads 1 and
    # 2 alike, so a tracked file missing from the working tree -- an ordinary
    # mid-edit state -- turned a found leak into "ok": the match was printed and
    # the step still passed. Branch on the status so an incomplete scan fails
    # loudly instead of reporting a clean tree it never finished reading.
    grep -InE -f <(grep -vE '^[[:space:]]*(#|$)' "${LEAK_PATTERNS}") -- "${leak_files[@]}"
    leak_rc=$?
    case "$leak_rc" in
      0) echo "LEAK: forbidden term(s) above"; fail=1 ;;
      1) echo "ok ($leak_n patterns)" ;;
      *) echo "FAIL: leak scan errored (grep exit $leak_rc) -- scanned set incomplete"; fail=1 ;;
    esac
  fi
else
  echo "SKIP (no LEAK_PATTERNS configured)"
fi

step "gitleaks (secrets)"
if command -v gitleaks >/dev/null 2>&1; then
  _g=$(gitleaks git --no-banner . 2>&1); _rc=$?
  printf '%s\n' "$_g"
  # gitleaks reports how many commits it scanned; zero is a pass over nothing.
  _n=$(printf '%s' "$_g" | sed -n 's/.*[^0-9]\([0-9][0-9]*\) commits scanned.*/\1/p' | tail -1)
  if [ "$_rc" -ne 0 ]; then fail=1
  elif [ -z "$_n" ]; then
    echo "FAIL: gitleaks exited 0 but its commit count could not be read -- output format changed?"; fail=1
  elif [ "$_n" -eq 0 ]; then echo "FAIL: gitleaks scanned 0 commits"; fail=1
  else echo "ok ($_n commits scanned)"; fi
else
  echo "SKIP (gitleaks not installed) — CI still runs it"
fi

step "REUSE (per-file SPDX licensing)"
if command -v reuse >/dev/null 2>&1; then
  _r=$(reuse lint 2>&1); _rc=$?
  # reuse reports "Files with copyright information: N / M". A lint over zero
  # files is a pass over nothing, and is reported as such.
  _n=$(printf '%s' "$_r" | sed -n 's/.*Files with copyright information: \([0-9][0-9]*\) \/ [0-9][0-9]*.*/\1/p' | tail -1)
  _d=$(printf '%s' "$_r" | sed -n 's/.*Files with copyright information: [0-9][0-9]* \/ \([0-9][0-9]*\).*/\1/p' | tail -1)
  if [ "$_rc" -ne 0 ]; then printf '%s\n' "$_r" | tail -20; fail=1
  elif [ -z "$_n" ]; then
    echo "FAIL: reuse exited 0 but its file count could not be read -- output format changed?"; fail=1
  elif [ "$_n" -eq 0 ]; then echo "FAIL: reuse checked 0 files"; fail=1
  else echo "ok ($_n/$_d files)"; fi
else
  echo "FAIL: reuse is not installed (pipx install reuse) — the licensing check cannot run"; fail=1
fi

step "vendored guards match their declared versions"
# The guards below are copies of missing-foss/dev-guards. This recomputes each
# one's hash and compares it to the version this repository claims, so a guard
# edited in place -- or left behind when the canonical copy moved on -- is a red
# check rather than a silent fork. Six copies of one guard drifting, with
# nothing reporting it, is why the canonical repository exists.
dev/guards/verify-vendored.sh || fail=1

step "Tracker references in published prose"
# Public docs must stand alone: an issue number that outlives the tracker it
# points at is worse than no citation. Excludes fenced blocks, inline code, hex
# colours and heading anchors -- a guard that false-positives gets switched
# off, and then protects nothing.
if python3 dev/guards/check-tracker-refs.py; then
  echo ok
else
  fail=1
fi

echo
if [ "$fail" -eq 0 ]; then echo "VERIFY OK"; else echo "VERIFY FAILED"; fi
exit "$fail"
