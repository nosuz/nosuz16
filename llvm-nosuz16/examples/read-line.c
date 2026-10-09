#include "nosuz16.h"

int main(void) {
  char line[32];
  unsigned int length = 0;
  while (length < sizeof(line) - 1u) {
    int byte = getc();
    if (byte == '\n') {
      break;
    }
    line[length++] = (char)byte;
  }
  line[length] = '\0';
  return printf("You typed: %s\n", line);
}
