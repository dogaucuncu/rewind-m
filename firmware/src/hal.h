/* Minimal STM32F407 register access — no vendor HAL, no CMSIS.
 *
 * Only what this project actually touches is defined here. Keeping it this
 * small is deliberate: every register the firmware reads is a potential source
 * of non-determinism that the recorder has to account for, so the surface is
 * kept auditable by hand. */

#ifndef REWIND_HAL_H
#define REWIND_HAL_H

#include <stdint.h>

#define REG32(addr) (*(volatile uint32_t *)(addr))

/* ---- RCC (reset and clock control) ------------------------------------- */
#define RCC_BASE        0x40023800u
#define RCC_AHB1ENR     REG32(RCC_BASE + 0x30u)
#define RCC_APB1ENR     REG32(RCC_BASE + 0x40u)
#define RCC_APB2ENR     REG32(RCC_BASE + 0x44u)

#define RCC_AHB1ENR_GPIODEN (1u << 3)
#define RCC_APB1ENR_TIM2EN  (1u << 0)
#define RCC_APB1ENR_USART2EN (1u << 17)

/* ---- USART2 -------------------------------------------------------------
 * USART2 rather than USART1: it is the console every STM32F4 Discovery example
 * in Renode's own test suite drives, so it is the best-exercised path in the
 * peripheral model. */
#define USART2_BASE     0x40004400u
#define USART2_SR       REG32(USART2_BASE + 0x00u)
#define USART2_DR       REG32(USART2_BASE + 0x04u)
#define USART2_BRR      REG32(USART2_BASE + 0x08u)
#define USART2_CR1      REG32(USART2_BASE + 0x0Cu)

#define USART_SR_TXE    (1u << 7)
#define USART_SR_RXNE   (1u << 5)
#define USART_CR1_RE    (1u << 2)
#define USART_CR1_TE    (1u << 3)
#define USART_CR1_UE    (1u << 13)

/* ---- TIM2 (periodic control-loop tick) ---------------------------------- */
#define TIM2_BASE       0x40000000u
#define TIM2_CR1        REG32(TIM2_BASE + 0x00u)
#define TIM2_DIER       REG32(TIM2_BASE + 0x0Cu)
#define TIM2_SR         REG32(TIM2_BASE + 0x10u)
#define TIM2_CNT        REG32(TIM2_BASE + 0x24u)
#define TIM2_PSC        REG32(TIM2_BASE + 0x28u)
#define TIM2_ARR        REG32(TIM2_BASE + 0x2Cu)

#define TIM_CR1_CEN     (1u << 0)
#define TIM_DIER_UIE    (1u << 0)
#define TIM_SR_UIF      (1u << 0)

/* ---- NVIC --------------------------------------------------------------- */
#define NVIC_ISER0      REG32(0xE000E100u)
#define NVIC_ISER1      REG32(0xE000E104u)

#define IRQ_TIM2        28u
#define IRQ_USART2      38u

static inline void nvic_enable(uint32_t irq)
{
    if (irq < 32u) {
        NVIC_ISER0 = (1u << irq);
    } else {
        NVIC_ISER1 = (1u << (irq - 32u));
    }
}

/* ---- DWT cycle counter --------------------------------------------------
 * The recorder timestamps every event with CYCCNT. On real silicon DEMCR.TRCENA
 * must be set before the DWT block responds; Renode's model does not require it
 * but we set it anyway so the same code works on hardware unchanged. */
#define DEMCR           REG32(0xE000EDFCu)
#define DEMCR_TRCENA    (1u << 24)

#define DWT_BASE        0xE0001000u
#define DWT_CTRL        REG32(DWT_BASE + 0x00u)
#define DWT_CYCCNT      REG32(DWT_BASE + 0x04u)
#define DWT_CTRL_CYCCNTENA (1u << 0)

static inline void dwt_init(void)
{
    DEMCR |= DEMCR_TRCENA;
    DWT_CYCCNT = 0u;
    DWT_CTRL |= DWT_CTRL_CYCCNTENA;
}

static inline uint32_t dwt_cycles(void)
{
    return DWT_CYCCNT;
}

/* ---- Simulated world ----------------------------------------------------
 * Two memory-mapped registers whose values the firmware cannot predict. Backed
 * in simulation by a seeded Python peripheral; on real hardware SENSOR_DR would
 * be an ADC data register and the jitter would come from the physical world
 * rather than a register. Reading either is non-deterministic by construction —
 * these are the inputs the recorder has to capture. */
#define SENSOR_BASE     0x50000000u
#define SENSOR_DR       REG32(SENSOR_BASE + 0x00u)
#define JITTER_DR       REG32(SENSOR_BASE + 0x04u)

void uart_init(void);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_put_u32(uint32_t v);
void uart_put_hex32(uint32_t v);

#endif /* REWIND_HAL_H */
