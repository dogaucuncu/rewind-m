/* Vector table and reset path for STM32F407, written in C.
 *
 * There is no assembly file in this project on purpose: the whole startup path
 * has to be readable by someone auditing what runs before main(), because
 * anything that executes before the recorder is initialised is invisible to a
 * replay. */

#include <stdint.h>
#include "hal.h"

extern uint32_t _estack;
extern uint32_t _sidata, _sdata, _edata, _sbss, _ebss;

int main(void);

void Reset_Handler(void);
void Default_Handler(void);

/* Handlers the project actually implements are declared weak here and defined
 * in main.c; everything else collapses onto Default_Handler. */
void TIM2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void USART2_IRQHandler(void) __attribute__((weak, alias("Default_Handler")));
void HardFault_Handler(void) __attribute__((weak, alias("Default_Handler")));

/* STM32F407: 16 system exceptions + 82 external interrupts. */
#define VECTOR_COUNT (16 + 82)

__attribute__((section(".isr_vector"), used))
void (*const g_vectors[VECTOR_COUNT])(void) = {
    [0]  = (void (*)(void))(&_estack),
    [1]  = Reset_Handler,
    [3]  = HardFault_Handler,
    /* External interrupts start at index 16. */
    [16 + IRQ_TIM2]   = TIM2_IRQHandler,
    [16 + IRQ_USART2] = USART2_IRQHandler,
};

void Reset_Handler(void)
{
    uint32_t *src = &_sidata;
    uint32_t *dst = &_sdata;

    while (dst < &_edata) {
        *dst++ = *src++;
    }
    for (dst = &_sbss; dst < &_ebss; dst++) {
        *dst = 0u;
    }

    (void)main();

    for (;;) {
    }
}

void Default_Handler(void)
{
    for (;;) {
    }
}
