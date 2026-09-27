#!/usr/bin/env bash
# Run every gate. Use before a release, and after any change to a compile stage or an extractor.
#
#   tools/run_gates.sh
#   PYTHON=.venv/bin/python tools/run_gates.sh     pick the interpreter
#
# The same gates run in CI (.github/workflows/ci.yml). See docs/GATES.md.
set -u

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
if ! "$PY" -c 'import pytest' >/dev/null 2>&1; then
  echo "ERROR: $PY has no pytest. Install it, or set PYTHON to an interpreter that has it:"
  echo "  PYTHON=/path/to/venv/bin/python tools/run_gates.sh"
  exit 2
fi
failed=0

run() {
  local label="$1"; shift
  printf '\n=== %s\n' "$label"
  if "$@"; then
    printf '    PASS  %s\n' "$label"
  else
    printf '    FAIL  %s\n' "$label"
    failed=$((failed + 1))
  fi
}

run "tests"                  "$PY" -m pytest
run "greenfield self-test"   "$PY" -m oto.cli verify
run "starter vocabularies"   "$PY" tools/check_ontologies.py
run "publishability"         "$PY" tools/check_publishable.py --strict
run "every module compiles"  "$PY" -m compileall -q oto tools tests

printf '\n----------------------------------------\n'
if [ "$failed" -gt 0 ]; then
  printf 'RESULT: %d gate(s) FAILED\n' "$failed"
  exit 1
fi
printf 'RESULT: all gates passed\n'
