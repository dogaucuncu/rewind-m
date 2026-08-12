#!/usr/bin/env bash
# Build the firmware, generate the per-seed platform, and run the Renode suite.
#
# Point RENODE_DIR at a Renode installation, or let the script find `renode-test`
# on PATH. See docs/SETUP.md — on Windows the winget package of Renode does not
# work; use WSL or the Linux CI.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="${SEED:-20260812}"
SUITE="${1:-${REPO}/tests/m0_smoke.robot}"

if [[ -n "${RENODE_DIR:-}" ]]; then
    RENODE_TEST="${RENODE_DIR}/renode-test"
elif command -v renode-test >/dev/null 2>&1; then
    RENODE_TEST="$(command -v renode-test)"
else
    echo "renode-test not found. Set RENODE_DIR or put renode-test on PATH." >&2
    echo "See docs/SETUP.md." >&2
    exit 1
fi

echo "==> building firmware"
make -C "${REPO}/firmware"

echo "==> generating platform for seed ${SEED}"
python3 "${REPO}/tools/gen_run.py" --seed "${SEED}"

echo "==> running ${SUITE}"
"${RENODE_TEST}" "${SUITE}"
