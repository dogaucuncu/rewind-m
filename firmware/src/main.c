/* M0 smoke test.
 *
 * Proves the four things the rest of the project is built on, and nothing more:
 *   1. the firmware boots and reaches main()
 *   2. USART1 output reaches the host
 *   3. the DWT cycle counter advances (the recorder's timestamp source)
 *   4. the simulated depth sensor returns values the firmware cannot predict
 *
 * The control loop, the deliberate race and the recorder arrive in M1 and M3. */

#include <stdint.h>
#include "hal.h"

#define SENSOR_SAMPLES 8u

int main(void)
{
    uint32_t before, after, i;

    uart_init();
    dwt_init();

    uart_puts("rewind-m M0 smoke test\r\n");

    before = dwt_cycles();
    for (i = 0u; i < SENSOR_SAMPLES; i++) {
        uint32_t sample = SENSOR_DR;
        uart_puts("sensor[");
        uart_put_u32(i);
        uart_puts("]=");
        uart_put_hex32(sample);
        uart_puts("\r\n");
    }
    after = dwt_cycles();

    uart_puts("dwt_delta=");
    uart_put_u32(after - before);
    uart_puts("\r\n");

    if (after == before) {
        /* A stuck cycle counter would silently break every timestamp in the
         * trace, so it fails loudly here rather than later. */
        uart_puts("FAIL dwt_stuck\r\n");
    } else {
        uart_puts("M0 OK\r\n");
    }

    for (;;) {
    }
}
