#include "recorder.h"
#include "hal.h"

/* Worst case for one record: kind byte, then two LEB128 varints of a 32-bit
 * value at five bytes each. */
#define TRACE_MAX_RECORD 11u

#define TRACE_VERSION 1u
#define TRACE_FLAG_TRUNCATED 0x01u

static uint8_t  g_buf[TRACE_CAPACITY];
static uint32_t g_len;
static uint32_t g_dropped;
static uint32_t g_last_cycles;

void recorder_init(void)
{
    g_len = 0u;
    g_dropped = 0u;
    g_last_cycles = dwt_cycles();
}

static void put_varint(uint32_t v)
{
    while (v >= 0x80u) {
        g_buf[g_len++] = (uint8_t)(v | 0x80u);
        v >>= 7;
    }
    g_buf[g_len++] = (uint8_t)v;
}

void recorder_event(uint8_t kind, uint32_t payload)
{
    uint32_t now = dwt_cycles();
    uint32_t delta = now - g_last_cycles;

    if ((TRACE_CAPACITY - g_len) < TRACE_MAX_RECORD) {
        /* Deliberately does not advance g_last_cycles: the next record that does
         * fit then carries a delta spanning the dropped events, so timestamps
         * after a gap stay correct relative to the start of the run. */
        g_dropped++;
        return;
    }

    g_last_cycles = now;
    g_buf[g_len++] = kind;
    put_varint(delta);
    put_varint(payload);
}

uint32_t recorder_length(void)
{
    return g_len;
}

uint32_t recorder_dropped(void)
{
    return g_dropped;
}

static void put_hex8(uint8_t b)
{
    static const char digits[] = "0123456789abcdef";
    uart_putc(digits[(b >> 4) & 0xFu]);
    uart_putc(digits[b & 0xFu]);
}

void recorder_flush_hex(void)
{
    uint32_t i;
    uint8_t header[8];
    uint8_t gap[TRACE_MAX_RECORD];
    uint32_t gap_len = 0u;
    uint32_t total;

    header[0] = (uint8_t)'R';
    header[1] = (uint8_t)'W';
    header[2] = (uint8_t)'M';
    header[3] = (uint8_t)'1';
    header[4] = (uint8_t)TRACE_VERSION;
    header[5] = (g_dropped != 0u) ? (uint8_t)TRACE_FLAG_TRUNCATED : 0u;
    header[6] = 0u;
    header[7] = 0u;

    /* The gap record is synthesised at flush rather than reserved in the buffer:
     * reserving space for it would mean dropping one more real event than
     * necessary in the case where it is never needed. */
    if (g_dropped != 0u) {
        uint32_t v = g_dropped;
        gap[gap_len++] = (uint8_t)TRACE_KIND_GAP;
        gap[gap_len++] = 0u;  /* delta: unknown across a gap, recorded as zero */
        while (v >= 0x80u) {
            gap[gap_len++] = (uint8_t)(v | 0x80u);
            v >>= 7;
        }
        gap[gap_len++] = (uint8_t)v;
    }

    total = (uint32_t)sizeof(header) + g_len + gap_len;

    uart_puts("TRACE BEGIN ");
    uart_put_u32(total);
    uart_puts("\r\n");

    for (i = 0u; i < (uint32_t)sizeof(header); i++) {
        put_hex8(header[i]);
    }
    for (i = 0u; i < g_len; i++) {
        put_hex8(g_buf[i]);
    }
    for (i = 0u; i < gap_len; i++) {
        put_hex8(gap[i]);
    }

    uart_puts("\r\nTRACE END\r\n");
}

uint32_t recorder_measure_cost(uint32_t iterations)
{
    uint32_t i;
    uint32_t before;
    uint32_t after;

    recorder_init();
    before = dwt_cycles();
    for (i = 0u; i < iterations; i++) {
        recorder_event((uint8_t)TRACE_KIND_SENSOR, i);
    }
    after = dwt_cycles();

    /* Discard the synthetic events: only the real run belongs in the trace. */
    recorder_init();

    return (after - before) / iterations;
}
