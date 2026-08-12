# Related work

Record and replay is a well-studied problem. This document exists so that nobody has to
guess what is new here and what is not.

## Prior work

### TARDIS — Trace And Replay Debugging In Sensornets (Purdue DCSL, IPSN 2015)

The closest prior work. Software-only, system-level record and replay for wireless sensor
network nodes. It identifies eight domains of non-determinism and compresses each with a
technique specialised for that domain, reaching a reported 5% runtime overhead and a log
growth rate of 0.5 bytes per thousand instructions — 85–96% smaller traces than the
control-flow record and replay techniques it compares against.

- Paper: <https://engineering.purdue.edu/dcsl/publications/papers/2015/tardis_matt_ipsn15.pdf>
- Code: <https://github.com/purdue-dcsl/tardis>

Targets TinyOS and Contiki on WSN-class motes.

### rr (Mozilla)

Deterministic record and replay for Linux userspace processes, with reverse execution in
GDB. Relies on hardware performance counters and OS-level control of scheduling — neither
of which exists on a bare-metal microcontroller.

### PANDA

Whole-system record and replay built on QEMU, aimed at dynamic analysis and reverse
engineering. Records at the emulator level, so the recording is not something that could
run on physical hardware.

## What this project does differently

| | TARDIS (2015) | rr | PANDA | rewind-m |
|---|---|---|---|---|
| Target | TinyOS / Contiki, WSN motes | Linux userspace | Whole system, QEMU guest | Bare-metal Cortex-M (STM32F4) |
| Recorder location | On device | OS + hardware counters | Emulator | **On device** |
| Runs without hardware | no | n/a | yes | **yes (Renode)** |
| Reproducible today by a stranger | research artifact | yes | yes | **`git clone` + `make`** |
| Recorder completeness | argued in the paper | n/a | n/a | **mechanically verified against emulator ground truth, per commit** |

The contribution worth pointing at is the last row. A recorder that silently drops events
produces replays that are confidently wrong, which is worse than no replay at all. Here the
in-firmware recorder is cross-checked on every CI run against an independent record of the
same events taken from Renode's own hooks, across many seeds. When the two disagree, the
build fails.

The second thing, less novel but practically useful: the whole setup runs with no hardware
and no licence, so the barrier to reproducing or extending it is a clone and a build.

## What this project does *not* claim

- It does not claim to have invented record and replay, on microcontrollers or anywhere else.
- It does not claim better compression than TARDIS. Trace size is measured in the same unit
  (bytes per thousand instructions) specifically so the comparison can be made honestly,
  in either direction.
- It does not claim real-time guarantees on physical silicon; see [LIMITS.md](LIMITS.md).
