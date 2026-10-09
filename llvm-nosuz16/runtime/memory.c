#include "nosuz16.h"

/* Packed byte operations preserve neighboring data. */
void __nosuz16_memcpy(unsigned int dest, unsigned int source,
                      unsigned int size) {
  while (size--) {
    nosuz16_stb(dest++, nosuz16_ldb(source++) & 0xffu);
  }
}

void __nosuz16_memset(unsigned int dest, unsigned int value,
                      unsigned int size) {
  value &= 0xffu;
  while (size--) {
    nosuz16_stb(dest++, value);
  }
}

void __nosuz16_memmove(unsigned int dest, unsigned int source,
                       unsigned int size) {
  if (dest > source && dest - source < size) {
    dest += size;
    source += size;
    while (size--) {
      nosuz16_stb(--dest, nosuz16_ldb(--source) & 0xffu);
    }
  } else {
    __nosuz16_memcpy(dest, source, size);
  }
}
