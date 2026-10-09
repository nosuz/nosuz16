#include "nosuz16.h"

/* C byte addresses are CPU word addresses. Always clear upper storage bits. */
void __nosuz16_memcpy(unsigned int dest, unsigned int source,
                      unsigned int size) {
  while (size--) {
    nosuz16_stw(dest++, nosuz16_ldw(source++) & 0xffu);
  }
}

void __nosuz16_memset(unsigned int dest, unsigned int value,
                      unsigned int size) {
  value &= 0xffu;
  while (size--) {
    nosuz16_stw(dest++, value);
  }
}

void __nosuz16_memmove(unsigned int dest, unsigned int source,
                       unsigned int size) {
  if (dest > source && dest - source < size) {
    dest += size;
    source += size;
    while (size--) {
      nosuz16_stw(--dest, nosuz16_ldw(--source) & 0xffu);
    }
  } else {
    __nosuz16_memcpy(dest, source, size);
  }
}
