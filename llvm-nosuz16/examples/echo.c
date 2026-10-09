#include "nosuz16.h"

/* Echo one received byte. With no input, getc waits indefinitely. */
int main(void) {
  return putc(getc());
}
