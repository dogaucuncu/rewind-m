#include "hal.h"

void uart_init(void)
{
    RCC_APB1ENR |= RCC_APB1ENR_USART2EN;
    /* Baud rate is irrelevant under emulation but a real board needs BRR set
     * before the peripheral is enabled; 16 MHz / 115200 ~= 0x8B. */
    USART2_BRR = 0x8Bu;
    USART2_CR1 = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

void uart_putc(char c)
{
    while ((USART2_SR & USART_SR_TXE) == 0u) {
    }
    USART2_DR = (uint32_t)(uint8_t)c;
}

void uart_puts(const char *s)
{
    while (*s != '\0') {
        uart_putc(*s++);
    }
}

void uart_put_u32(uint32_t v)
{
    char buf[11];
    int i = 0;

    if (v == 0u) {
        uart_putc('0');
        return;
    }
    while (v > 0u) {
        buf[i++] = (char)('0' + (v % 10u));
        v /= 10u;
    }
    while (i > 0) {
        uart_putc(buf[--i]);
    }
}

void uart_put_hex32(uint32_t v)
{
    static const char digits[] = "0123456789abcdef";
    int shift;

    uart_puts("0x");
    for (shift = 28; shift >= 0; shift -= 4) {
        uart_putc(digits[(v >> shift) & 0xFu]);
    }
}
