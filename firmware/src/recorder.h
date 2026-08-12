/* The recorder: the part that would have to run on real silicon.
 *
 * It lives inside the firmware and is subject to the constraints that implies -
 * a fixed cycle budget per event, a bounded buffer, and no way to ask the host
 * for help. The emulator-side oracle exists to check this code, not to replace
 * it; recording from outside the CPU would have been easier and would have
 * produced a tool that could never leave the simulator.
 *
 * Encoding is specified in docs/TRACE-FORMAT.md.
 */

#ifndef REWIND_RECORDER_H
#define REWIND_RECORDER_H

#include <stdint.h>

#define TRACE_KIND_SENSOR 'S'
#define TRACE_KIND_JITTER 'J'
#define TRACE_KIND_IRQ    'I'
#define TRACE_KIND_GAP    'G'

/* Sized so a full 200-tick run fits without dropping: 609 records at a worst
 * case of 11 bytes each. A real deployment would have far less RAM to spare and
 * would lean on the gap path instead; that path is exercised deliberately by
 * building with a small TRACE_CAPACITY rather than by hoping for an overflow. */
#ifndef TRACE_CAPACITY
#define TRACE_CAPACITY 16384u
#endif

void recorder_init(void);

/* Appends one event, stamped with the DWT cycle delta since the previous one.
 * Never blocks and never fails loudly: if the buffer is full the event is
 * counted as dropped and the trace is marked truncated at flush. Losing events
 * silently would be worse than either. */
void recorder_event(uint8_t kind, uint32_t payload);

uint32_t recorder_length(void);
uint32_t recorder_dropped(void);

/* Writes the trace to the UART as hex between markers. Hex rather than raw
 * bytes because the transport is shared with human-readable output; the size
 * that gets reported is the binary length, not what the wire carried. */
void recorder_flush_hex(void);

/* Cost of one recorded event, in cycles, measured in isolation before the run
 * starts. Includes the loop that drives it, so it is an upper bound. */
uint32_t recorder_measure_cost(uint32_t iterations);

#endif /* REWIND_RECORDER_H */
