/* M1: a depth-hold control loop with a deliberate, intermittent race.
 *
 * The TIM2 ISR samples the depth sensor and publishes it as a two-word value:
 * the sample and its bitwise complement. Publishing is NOT atomic. The control
 * loop reads the first word, spends a few cycles computing, then reads the
 * second. If the ISR lands in that gap, the loop sees one word from tick N and
 * the other from tick N+1, and the consistency check fails.
 *
 * This is the shape of bug this project exists for: it depends entirely on where
 * an interrupt landed relative to the main loop, so it appears in a small
 * fraction of runs and vanishes under a debugger.
 *
 * The firmware reports what happened; tools/campaign.py runs many seeds and
 * measures how often it happens. No number about the failure rate is written
 * down anywhere that was not measured.
 */

#include <stdint.h>
#include "hal.h"
#include "recorder.h"

/* ---- self-test ---------------------------------------------------------- */
#define SELFTEST_SAMPLES 8u

/* ---- control loop ------------------------------------------------------- */
#define TARGET_TICKS  200u        /* ISR ticks per run */
#define TICK_BASE     2000u       /* TIM2 runs at 10 MHz -> 200 us base period */
#define JITTER_MASK   0x1FFu      /* plus 0..511 ticks of seeded jitter */
#define SETPOINT      2048
#define KP            4
#define KI            1

/* How much non-critical work the controller does per iteration, outside the
 * two shared-state reads. This is the knob that sets how often the race is hit:
 * the fault needs the ISR to land in the short window between the reads, so
 * widening everything else makes it rarer. Real controllers spend most of their
 * time exactly here - filtering, output shaping, telemetry - so this is a model
 * of a real cost, not padding for its own sake.
 *
 * The default is not a guess: it comes from a sweep, and at 4096 the fault
 * appears in 13 of 400 runs on the build that ships. That is the regime this tool exists for - rare
 * enough that you cannot catch it by running the thing again, common enough to
 * be real. Zero is a valid setting and means the baseline, nothing outside the
 * window.
 *
 * docs/MEASUREMENTS.md carries the numbers and their provenance, including one
 * retracted set. */
#ifndef CONTROL_WORK
#define CONTROL_WORK  4096
#endif

/* Bounds the run even if TIM2 never fires, so a broken timer model shows up as
 * a reported failure instead of a CI job that hangs until the runner times out. */
#define MAX_ITERS     20000000u

/* Published by the ISR, consumed by the control loop. Two words that are only
 * consistent if they were written by the same tick. */
static volatile uint32_t g_depth;
static volatile uint32_t g_depth_inv;
static volatile uint32_t g_ticks;

/* Counts of the non-deterministic inputs this run consumed. The oracle counts
 * the same events independently from outside the CPU, and the two must agree
 * exactly - that check is what makes the recorder's completeness testable
 * rather than asserted. See docs/TRACE-FORMAT.md.
 *
 * No locking: the self-test and the priming read happen before the timer is
 * enabled, and after that only the ISR touches these. */
static volatile uint32_t g_sensor_reads;
static volatile uint32_t g_jitter_reads;

/* Cortex-M exception number of the handler currently running. Cheap - one
 * instruction - which matters because it is read inside the ISR. */
static inline uint32_t ipsr(void)
{
    uint32_t value;
    __asm__ volatile ("mrs %0, ipsr" : "=r" (value));
    return value & 0x1FFu;
}

static uint32_t read_sensor(void)
{
    uint32_t value = SENSOR_DR;
    g_sensor_reads++;
    /* Recorded after the read, so the trace carries the value the firmware
     * actually saw. The oracle hooks the same access on its way out. */
    recorder_event((uint8_t)TRACE_KIND_SENSOR, value);
    return value;
}

static uint32_t read_jitter(void)
{
    uint32_t value = JITTER_DR;
    g_jitter_reads++;
    recorder_event((uint8_t)TRACE_KIND_JITTER, value);
    return value;
}

void TIM2_IRQHandler(void);

void TIM2_IRQHandler(void)
{
    uint32_t d;

    /* First thing in the handler, so it lands in the same place in the sequence
     * as the oracle's interrupt-begin hook. */
    recorder_event((uint8_t)TRACE_KIND_IRQ, ipsr());

    TIM2_SR = ~TIM_SR_UIF;

    d = read_sensor();

    g_depth = d;
    /* The bug. A reader scheduled between these two stores observes a torn
     * pair. Disabling interrupts around them, or publishing through a single
     * word, would both fix it. */
    g_depth_inv = ~d;

    /* Variable-rate sampling: the next period carries seeded jitter, so the ISR
     * does not stay phase-locked to the control loop. */
    TIM2_ARR = TICK_BASE + (read_jitter() & JITTER_MASK);

    g_ticks++;
}

static void tim2_init(void)
{
    RCC_APB1ENR |= RCC_APB1ENR_TIM2EN;
    TIM2_PSC = 0u;
    TIM2_ARR = TICK_BASE;
    TIM2_DIER = TIM_DIER_UIE;
    TIM2_CR1 = TIM_CR1_CEN;
    nvic_enable(IRQ_TIM2);
}

/* Checks the instrumentation the rest of the project depends on: the cycle
 * counter is running and the sensor is actually varying. Both are silent
 * failure modes that would invalidate every trace taken afterwards. */
static void selftest(void)
{
    uint32_t before, after, i;

    uart_puts("rewind-m self-test\r\n");

    before = dwt_cycles();
    for (i = 0u; i < SELFTEST_SAMPLES; i++) {
        uint32_t sample = read_sensor();
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
        uart_puts("FAIL dwt_stuck\r\n");
    } else {
        uart_puts("selftest OK\r\n");
    }
}

int main(void)
{
    uint32_t iters = 0u;
    uint32_t torn = 0u;
    int32_t integral = 0;
    int32_t control_sum = 0;

    uart_init();
    dwt_init();

    /* Cost of the recorder, measured in isolation before anything real is
     * recorded.
     *
     * This must run BEFORE the self-test. The measurement resets the recorder
     * when it finishes, so measuring afterwards silently discards the
     * self-test's reads: the device trace then starts eight events later than
     * the oracle's, and every subsequent comparison is off by that much. */
    uart_puts("recorder cycles_per_event=");
    uart_put_u32(recorder_measure_cost(256u));
    uart_puts(" capacity=");
    uart_put_u32((uint32_t)TRACE_CAPACITY);
    uart_puts("\r\n");

    recorder_init();
    selftest();


    /* Publish a consistent pair before the first tick. Without this the loop
     * sees g_depth == 0 against g_depth_inv == 0 - which fails the check - and
     * every iteration before the first ISR counts as a tear. That artefact put
     * the measured failure rate at 100% and hid the real race completely. */
    {
        uint32_t seed_sample = read_sensor();
        g_depth = seed_sample;
        g_depth_inv = ~seed_sample;
    }

    tim2_init();

    while (g_ticks < TARGET_TICKS) {
        uint32_t depth;
        uint32_t depth_inv;
        int32_t error;
        int32_t control;

        depth = g_depth;

        /* The window: the few instructions between the two reads of the shared
         * pair. An ISR landing here publishes a new sample in the middle of our
         * snapshot. */
        error = SETPOINT - (int32_t)depth;

        depth_inv = g_depth_inv;

        if (depth != (uint32_t)~depth_inv) {
            torn++;
        }

        /* Everything below is outside the window. */
        integral += error;
        if (integral > 100000) {
            integral = 100000;
        } else if (integral < -100000) {
            integral = -100000;
        }
        control = (KP * error) + ((KI * integral) >> 4);
        control_sum += control >> 8;

#if CONTROL_WORK > 0
        {
            uint32_t work;
            for (work = 0u; work < (uint32_t)CONTROL_WORK; work++) {
                control_sum += (int32_t)(work ^ (uint32_t)control);
            }
        }
#endif

        iters++;
        if (iters >= MAX_ITERS) {
            uart_puts("RUN FAIL no_ticks\r\n");
            /* Flush before stopping: the run that never got a tick is
             * exactly the one whose recorded inputs explain why. */
            recorder_flush_hex();
            for (;;) {
            }
        }
    }

    /* Stop the tick before reporting. The run continues to be emulated after
     * main() finishes, so a timer left running keeps feeding the ISR and the
     * oracle keeps recording reads the firmware never counted - the two totals
     * then disagree by however long the emulation happened to run on. Disabling
     * at the NVIC as well as the timer means a pending interrupt cannot slip
     * through between the two writes. */
    TIM2_CR1 = 0u;
    TIM2_DIER = 0u;
    nvic_disable(IRQ_TIM2);

    uart_puts("control ticks=");
    uart_put_u32(g_ticks);
    uart_puts(" iters=");
    uart_put_u32(iters);
    uart_puts(" torn=");
    uart_put_u32(torn);
    uart_puts(" checksum=");
    uart_put_hex32((uint32_t)control_sum);
    uart_puts("\r\n");

    /* Cross-checked against the oracle's independent count. */
    uart_puts("reads sensor=");
    uart_put_u32(g_sensor_reads);
    uart_puts(" jitter=");
    uart_put_u32(g_jitter_reads);
    uart_puts("\r\n");

    uart_puts("trace bytes=");
    uart_put_u32(recorder_length());
    uart_puts(" dropped=");
    uart_put_u32(recorder_dropped());
    uart_puts("\r\n");
    recorder_flush_hex();

    if (torn == 0u) {
        uart_puts("RUN OK\r\n");
    } else {
        uart_puts("RUN FAIL torn=");
        uart_put_u32(torn);
        uart_puts("\r\n");
    }

    for (;;) {
    }
}
