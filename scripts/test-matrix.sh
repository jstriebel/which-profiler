#!/usr/bin/env bash
# Multi-Python test matrix for which-profiler.
#
# Runs the root CLI's test suite against every supported interpreter (3.10-3.15)
# in an isolated per-version venv under .venvs/, so the dev venv (.venv, pinned
# to the version in .python-version) is never resynced. Also runs the
# examples/image_analysis sub-project's own test suite on 3.14 (its floor,
# per its pyproject requires-python), and confirms a_pure_python.py's 3.15
# smoke coverage is exercised (it's stdlib-only and runs directly in the root
# suite via tests/test_a_pure_python.py, no separate step needed here).
#
# The support matrix is DATA, not a pass/fail gate on its own: a REQUIRED
# cell failing is a hard error, but 3.15 (still prerelease) is allowed to be
# a RECORDED SKIP if dependency wheels aren't available for it yet.
#
# Usage: scripts/test-matrix.sh
# Run from anywhere; paths are resolved relative to the repo root.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ROOT_PYTHONS=(3.10 3.11 3.12 3.13 3.14 3.15)
EXAMPLES_PYTHON=3.14
PRERELEASE_PYTHONS=(3.15) # allowed to degrade a dep-install failure to a skip

# name -> status ("pass" / "fail" / "skip"), and a one-line detail message.
declare -A RESULT_STATUS
declare -A RESULT_DETAIL
ANY_REQUIRED_FAILURE=0

record() {
    local name="$1" status="$2" detail="$3"
    RESULT_STATUS["$name"]="$status"
    RESULT_DETAIL["$name"]="$detail"
}

is_prerelease() {
    local v="$1"
    for p in "${PRERELEASE_PYTHONS[@]}"; do
        [[ "$p" == "$v" ]] && return 0
    done
    return 1
}

run_root_cell() {
    local ver="$1"
    local env_dir="$REPO_ROOT/.venvs/py${ver}"
    local log
    log="$(mktemp)"

    echo "=== root tests: python ${ver} ==="
    if UV_PROJECT_ENVIRONMENT="$env_dir" uv run --python "$ver" pytest tests/ -q \
        >"$log" 2>&1; then
        local summary
        summary="$(grep -Eo '[0-9]+ passed(, [0-9]+ skipped)?' "$log" | tail -1 || true)"
        summary="${summary:-ok}"
        record "root-py${ver}" "pass" "$summary"
        tail -5 "$log"
    else
        local rc=$?
        # 3.15 is prerelease: if the failure happened before any test ran
        # (dependency resolution/install, e.g. no wheels yet for typer/click
        # on this interpreter), record it as a loud SKIP instead of a hard
        # failure. A real test failure on 3.15 still fails the matrix.
        if is_prerelease "$ver" && ! grep -Eq '[0-9]+ (passed|failed|error)' "$log"; then
            echo "!!! python ${ver}: dependency install failed on prerelease interpreter – RECORDED SKIP !!!"
            tail -15 "$log"
            record "root-py${ver}" "skip" "prerelease dep-install failure"
        else
            echo "!!! python ${ver}: root tests FAILED (rc=${rc}) !!!"
            tail -30 "$log"
            record "root-py${ver}" "fail" "exit ${rc}"
            ANY_REQUIRED_FAILURE=1
        fi
    fi
    rm -f "$log"
}

run_examples_cell() {
    local ver="$EXAMPLES_PYTHON"
    local log
    log="$(mktemp)"

    echo "=== examples/image_analysis tests: python ${ver} ==="
    if (cd "$REPO_ROOT/examples/image_analysis" && uv run pytest -q) \
        >"$log" 2>&1; then
        local summary
        summary="$(grep -Eo '[0-9]+ passed(, [0-9]+ skipped)?' "$log" | tail -1 || true)"
        summary="${summary:-ok}"
        record "examples-py${ver}" "pass" "$summary"
        tail -5 "$log"
    else
        local rc=$?
        echo "!!! examples/image_analysis on python ${ver}: FAILED (rc=${rc}) !!!"
        tail -30 "$log"
        record "examples-py${ver}" "fail" "exit ${rc}"
        ANY_REQUIRED_FAILURE=1
    fi
    rm -f "$log"
}

for ver in "${ROOT_PYTHONS[@]}"; do
    run_root_cell "$ver"
done

run_examples_cell

# a_pure_python.py on 3.15: it's stdlib-only and is already exercised
# directly (no examples/image_analysis venv needed) by
# tests/test_a_pure_python.py, which runs inside the root-py3.15 cell above.
# Record that coverage explicitly in the summary rather than re-running it.
if [[ "${RESULT_STATUS[root-py3.15]:-}" == "pass" ]]; then
    record "a_pure_python-py3.15" "pass" "covered by tests/test_a_pure_python.py in root-py3.15 cell"
elif [[ "${RESULT_STATUS[root-py3.15]:-}" == "skip" ]]; then
    record "a_pure_python-py3.15" "skip" "root-py3.15 cell was skipped"
else
    record "a_pure_python-py3.15" "fail" "root-py3.15 cell failed"
fi

echo
echo "==================== test matrix summary ===================="
printf '%-28s %-6s %s\n' "cell" "status" "detail"
printf '%-28s %-6s %s\n' "----" "------" "------"
for name in "root-py3.10" "root-py3.11" "root-py3.12" "root-py3.13" "root-py3.14" "root-py3.15" \
    "examples-py3.14" "a_pure_python-py3.15"; do
    status="${RESULT_STATUS[$name]:-missing}"
    detail="${RESULT_DETAIL[$name]:-}"
    printf '%-28s %-6s %s\n' "$name" "$status" "$detail"
done
echo "================================================================"

if [[ "$ANY_REQUIRED_FAILURE" -ne 0 ]]; then
    echo "test matrix: FAILED (one or more required cells failed)"
    exit 1
fi

echo "test matrix: PASSED (skips, if any, were recorded prerelease exceptions)"
