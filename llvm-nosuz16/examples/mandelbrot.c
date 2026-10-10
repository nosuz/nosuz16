#include "nosuz16.h"

/* Layout and iteration convention of the ASCIIART benchmark:
 * https://haserin09.la.coocan.jp/asciiart.html
 * x = -39..39 times 0.0458; y = -12..12 times 0.08333; 16 updates.
 * Print hexadecimal escape counts, or a space for a bounded point.
 *
 * Q16 values use two 16-bit fields, avoiding unsupported C long/float
 * arithmetic. A value is whole + fraction/65536, with a signed whole
 * part and a nonnegative fraction (so -0.5 is {-1, 32768}). Volatile
 * fields prevent LLVM from merging the two fields into a 32-bit access. */
typedef unsigned short word;
typedef struct {
  volatile short whole;
  volatile word fraction;
} fixed;

#define MAX_ITERATIONS 16

/* Fractional fields of rounded Q16 coordinates, calculated independently
 * for each sample instead of accumulating a rounded step. Positive x has
 * whole part 1 from sample 22 onward; positive y always has whole part 0. */
static const word x_fraction[40] = {
    0u, 3002u, 6003u, 9005u, 12006u, 15008u, 18009u, 21011u,
    24012u, 27014u, 30015u, 33017u, 36019u, 39020u, 42022u, 45023u,
    48025u, 51026u, 54028u, 57029u, 60031u, 63033u, 498u, 3500u,
    6501u, 9503u, 12504u, 15506u, 18507u, 21509u, 24510u, 27512u,
    30514u, 33515u, 36517u, 39518u, 42520u, 45521u, 48523u, 51524u};
static const word y_fraction[13] = {
    0u, 5461u, 10922u, 16383u, 21844u, 27306u, 32767u,
    38228u, 43689u, 49150u, 54611u, 60072u, 65533u};

void fixed_negate(fixed *value) {
  value->whole = -value->whole - (value->fraction != 0);
  value->fraction = (word)(0u - value->fraction);
}

/* Helpers allow the destination to alias either operand. External linkage
 * keeps the supported C calling convention when a helper is not inlined. */
void fixed_add(const fixed *a, const fixed *b, fixed *result) {
  word fraction = (word)(a->fraction + b->fraction);
  short whole = a->whole + b->whole + (fraction < a->fraction);
  result->whole = whole;
  result->fraction = fraction;
}

void fixed_subtract(const fixed *a, const fixed *b, fixed *result) {
  short whole = a->whole - b->whole - (a->fraction < b->fraction);
  word fraction = (word)(a->fraction - b->fraction);
  result->whole = whole;
  result->fraction = fraction;
}

/* High half of an unsigned 16x16 product, using four 8x8 products.
 * Every intermediate fits 16 bits, including the cross-byte carry.
 * Keep partial products observable so LLVM cannot replace this helper
 * with a 32-bit multiply, which this backend does not yet support. */
__attribute__((noinline)) word fixed_multiply_high(word a, word b) {
  word a0 = a & 255u;
  word a1 = a >> 8;
  word b0 = b & 255u;
  word b1 = b >> 8;
  volatile word p0 = a0 * b0;
  volatile word p1 = a1 * b0;
  volatile word p2 = a0 * b1;
  volatile word p3 = a1 * b1;
  word carry = (p0 >> 8) + (p1 & 255u) + (p2 & 255u);
  return p3 + (p1 >> 8) + (p2 >> 8) + (carry >> 8);
}

/* Squaring needs only three partial products: both cross terms are equal. */
__attribute__((noinline)) word fixed_square_high(word a) {
  word low = a & 255u;
  word high = a >> 8;
  volatile word p0 = low * low;
  volatile word p1 = low * high;
  volatile word p2 = high * high;
  word carry = (p0 >> 8) + 2u * (p1 & 255u);
  return p2 + 2u * (p1 >> 8) + (carry >> 8);
}

/* Square a component whose magnitude is at most two. Keep this shared:
 * inlining every square makes the program much larger for little speedup. */
__attribute__((noinline)) void fixed_square(const fixed *a, fixed *result) {
  fixed magnitude;
  magnitude.whole = a->whole;
  magnitude.fraction = a->fraction;
  if (magnitude.whole < 0) {
    fixed_negate(&magnitude);
  }
  word high = (word)magnitude.whole;
  word low = magnitude.fraction;
  word fraction = fixed_square_high(low);
  word whole = high == 2u ? 4u : high;
  word i;
  for (i = 0; i < 2u * high; ++i) {
    word sum = (word)(fraction + low);
    whole += sum < fraction;
    fraction = sum;
  }
  result->whole = (short)whole;
  result->fraction = fraction;
}

/* Multiply the small signed Q16 values used here; truncate toward zero. */
void fixed_multiply(const fixed *a, const fixed *b, fixed *result) {
  fixed left, right;
  left.whole = a->whole;
  left.fraction = a->fraction;
  right.whole = b->whole;
  right.fraction = b->fraction;
  int negative = (left.whole < 0) != (right.whole < 0);
  if (left.whole < 0) {
    fixed_negate(&left);
  }
  if (right.whole < 0) {
    fixed_negate(&right);
  }

  word ah = (word)left.whole;
  word bh = (word)right.whole;
  word al = left.fraction;
  word bl = right.fraction;
  word fraction = fixed_multiply_high(al, bl);
  /* Orbit components are bounded by two before multiplication. Add the
   * integer cross terms at most twice, rather than doing general products. */
  word whole = 0;
  word i;
  for (i = 0; i < ah; ++i) {
    word sum = (word)(fraction + bl);
    whole += bh + (sum < fraction);
    fraction = sum;
  }
  for (i = 0; i < bh; ++i) {
    word sum = (word)(fraction + al);
    whole += sum < fraction;
    fraction = sum;
  }
  result->whole = (short)whole;
  result->fraction = fraction;
  if (negative) {
    fixed_negate(result);
  }
}

char mandelbrot_pixel(const fixed *cx, const fixed *cy) {
  static const char digits[] = "0123456789ABCDEF";
  fixed x, y;
  x.whole = cx->whole;
  x.fraction = cx->fraction;
  y.whole = cy->whole;
  y.fraction = cy->fraction;
  fixed xx, yy, xy, radius;
  unsigned int iteration;

  /* Reuse each escape check's squares in the next update. */
  fixed_square(&x, &xx);
  fixed_square(&y, &yy);
  for (iteration = 0; iteration < MAX_ITERATIONS; ++iteration) {
    fixed_multiply(&x, &y, &xy);
    fixed_subtract(&xx, &yy, &x);
    fixed_add(&x, cx, &x);
    fixed_add(&xy, &xy, &y);
    fixed_add(&y, cy, &y);

    /* Check before squaring the new values. Escaped components can be
     * larger than two; avoid unnecessary products outside that range. */
    if (x.whole < -2 || x.whole > 2 ||
        (x.whole == 2 && x.fraction != 0) ||
        y.whole < -2 || y.whole > 2 ||
        (y.whole == 2 && y.fraction != 0)) {
      return digits[iteration];
    }
    fixed_square(&x, &xx);
    fixed_square(&y, &yy);
    fixed_add(&xx, &yy, &radius);
    if (radius.whole > 4 || (radius.whole == 4 && radius.fraction != 0)) {
      return digits[iteration];
    }
  }
  return ' ';
}

int main(void) {
  int row, column;
  fixed cx, cy;
  /* Run the orbit calculation independently for every pixel. */
  for (row = -12; row <= 12; ++row) {
    cy.whole = 0;
    cy.fraction = y_fraction[row < 0 ? -row : row];
    if (row < 0) {
      fixed_negate(&cy);
    }
    for (column = -39; column <= 39; ++column) {
      int sample = column < 0 ? -column : column;
      cx.whole = sample >= 22;
      cx.fraction = x_fraction[sample];
      if (column < 0) {
        fixed_negate(&cx);
      }
      putc(mandelbrot_pixel(&cx, &cy));
    }
    putc('\n');
  }
  return 0;
}
