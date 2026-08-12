# Limits

What this project does not do, and where its guarantees stop. Kept in the repository rather
than discovered by the reader, because a replay tool that overstates its coverage is worse
than none.

## Sources of non-determinism

| Source | Captured | Note |
|---|---|---|
| Sensor data register reads | planned (M3) | the primary input; seeded per run |
| Interrupt delivery position | planned (M3) | timestamped with DWT CYCCNT |
| UART receive timing and framing | planned (M3) | |
| DMA transfers racing the main loop | **no** | out of scope for v1 |
| RTOS task scheduling | **no** | v1 is bare metal by construction |
| Multi-core / inter-core races | **no** | single Cortex-M4 |
| Analog noise, supply brown-out, bus contention | **no** | not modelled by the simulator |

Anything in the "no" rows can make a real fault unreproducible. The replay engine's job is
to notice when that has happened and say so, rather than to produce a confident but wrong
replay — see the divergence detector below.

## Simulation, not silicon

Renode is a functional simulator, not cycle-accurate. Two consequences:

1. **DWT CYCCNT values do not match what the same firmware would produce on a real board.**
   Replay therefore does not depend on cycle counts being reproducible; it aligns on the
   recorded event sequence and uses timestamps only as ordering information.
2. **Real-time behaviour cannot be proven here.** The recorder's cost is measured in cycles
   and gated in CI, but "the instrumented firmware still meets its deadlines on physical
   hardware" is a claim this repository does not support. Validating it needs a board.

## Divergence, overflow, and other honest failures

- **Ring buffer overflow.** If the recorder cannot keep up, the overflow is written into the
  trace as an explicit gap marker. Replay stops at that marker rather than continuing past a
  hole and pretending the result is faithful.
- **Replay divergence.** During replay, every recorded event is checked against what the
  firmware actually asks for. If event N does not match, replay fails loudly. A silently
  wrong replay is the one outcome this project treats as unacceptable.
- **The seed never reaches replay.** Replay reads the trace and nothing else. This is what
  makes the reproduction claim meaningful rather than circular, and CI enforces it.

## Scope

One board (STM32F4 Discovery), one CPU, bare metal, C. Everything above the "no" line stays
out until the core is proven.
