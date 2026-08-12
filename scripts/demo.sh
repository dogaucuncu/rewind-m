#!/usr/bin/env bash
# Record a run that fails, then reproduce it from the trace alone.
#
# This is the whole project in about a minute. Seed 6 is one the campaign found
# the race in; any of the seeds in docs/MEASUREMENTS.md will do.
#
#   scripts/demo.sh          # seed 6
#   scripts/demo.sh 144      # some other failing run
#
# Needs RENODE_DIR set, or renode on PATH. See docs/SETUP.md.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEED="${1:-6}"

rule() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

rule "Building the firmware"
make -C "${REPO}/firmware" >/dev/null
make -C "${REPO}/firmware" size

rule "Recording seed ${SEED}, then replaying it from the trace alone"
echo "The recording phase knows the seed. The replay phase is handed only the"
echo "values in the trace - tools/gen_run.py refuses to build a replay"
echo "peripheral that can reach a seed at all."
echo
python3 "${REPO}/tools/replay.py" --seeds "${SEED}" --require-torn

TRACE="${REPO}/build/replay/${SEED}-record/trace.bin"
if [[ -f "${TRACE}" ]]; then
    rule "What the trace actually contains"
    python3 "${REPO}/tools/show_trace.py" "${TRACE}" --head 12
fi

rule "What just happened"
cat <<'EOF'
A run that fails in roughly 3% of seeds was recorded, and then reproduced from
its trace with the failure intact: same torn count, same control checksum, same
verdict, and an event-for-event identical trace the second time round.

The failure depends on where an interrupt landed relative to two instructions in
the control loop. Running the firmware again would not find it. Replaying the
trace finds it every time.

  docs/MEASUREMENTS.md  every number, and which build it came from
  docs/LIMITS.md        what this does not do, including the fact that the
                        recorder changes the timing it records
EOF
