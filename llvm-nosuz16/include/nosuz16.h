#ifndef NOSUZ16_H
#define NOSUZ16_H

#ifndef __NOSUZ16__
#error "nosuz16.h requires clang --target=nosuz16"
#endif

/* v2.5: packed bytes; int and pointers use one aligned 16-bit word.
 * All addresses, including raw I/O addresses, are byte addresses. */
typedef unsigned int nosuz16_word;

/* Reads are observable even when discarded: FF00 consumes UART input.
 * Neither declaration may be marked pure or const. */
extern nosuz16_word
nosuz16_ldw(nosuz16_word address) __asm__("llvm.nosuz16.ldw");
extern void nosuz16_stw(nosuz16_word address,
                        nosuz16_word value) __asm__("llvm.nosuz16.stw");

/* Byte operations zero-extend loads and preserve the neighboring byte. */
extern nosuz16_word
nosuz16_ldb(nosuz16_word address) __asm__("llvm.nosuz16.ldb");
extern void nosuz16_stb(nosuz16_word address,
                        nosuz16_word value) __asm__("llvm.nosuz16.stb");

#define NOSUZ16_UART_TXRX ((nosuz16_word)0xff00u)
#define NOSUZ16_UART_STATUS ((nosuz16_word)0xff02u)
#define NOSUZ16_VIDEO_MODE ((nosuz16_word)0xff10u)

/* Bare-metal UART API: no FILE stream or EOF. getc waits for RX_READY and
 * returns 0..255 (including NUL). putc waits for TX_READY, sends the low
 * eight bits, and returns the transmitted byte. */
int getc(void);
int putc(int c);

/* Literal formats only: %% %d %i %u %x %X %o %c and %s (C strings).
 * Integer arguments are 16-bit. No width, precision, length modifiers, or
 * floating-point formatting. Returns the number of bytes written. */
int printf(const char *format, ...) __attribute__((format(printf, 1, 2)));

#endif
