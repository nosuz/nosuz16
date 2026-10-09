#include "nosuz16.h"

int getc(void) {
  while ((nosuz16_ldw(NOSUZ16_UART_STATUS) & 1u) == 0u) {
  }
  return nosuz16_ldw(NOSUZ16_UART_TXRX) & 0xffu;
}

int putc(int c) {
  unsigned int byte = (unsigned int)c & 0xffu;
  while ((nosuz16_ldw(NOSUZ16_UART_STATUS) & 2u) == 0u) {
  }
  nosuz16_stw(NOSUZ16_UART_TXRX, byte);
  return byte;
}

/* Fixed-argument helpers used by the compiler's literal printf expansion. */
int __nosuz16_print_unsigned(unsigned int value, unsigned int base,
                             unsigned int uppercase) {
  int count = 0;
  if (value >= base) {
    count = __nosuz16_print_unsigned(value / base, base, uppercase);
  }
  unsigned int digit = value % base;
  putc(digit < 10u ? '0' + digit : (uppercase ? 'A' : 'a') + digit - 10u);
  return count + 1;
}

int __nosuz16_print_signed(int value) {
  if (value < 0) {
    putc('-');
    /* Unsigned subtraction also handles INT_MIN without signed overflow. */
    return 1 + __nosuz16_print_unsigned(0u - (unsigned int)value, 10u, 0u);
  }
  return __nosuz16_print_unsigned((unsigned int)value, 10u, 0u);
}

int __nosuz16_print_string(unsigned int address) {
  int count = 0;
  unsigned int byte;
  while ((byte = nosuz16_ldb(address++) & 0xffu) != 0u) {
    putc(byte);
    ++count;
  }
  return count;
}
