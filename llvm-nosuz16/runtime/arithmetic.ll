; Software i16 arithmetic; all addresses and stacks follow the Nosuz16 ABI.
; LLVM IR division by zero and signed INT_MIN/-1 remain undefined.
target triple = "nosuz16"

define i16 @__mulhi3(i16 %a, i16 %b) {
entry:
  br label %loop
loop:
  %x = phi i16 [%a, %entry], [%nextx, %loop]
  %y = phi i16 [%b, %entry], [%nexty, %loop]
  %sum = phi i16 [0, %entry], [%nextsum, %loop]
  %bit = and i16 %y, 1
  %include = icmp ne i16 %bit, 0
  %term = select i1 %include, i16 %x, i16 0
  %nextsum = add i16 %sum, %term
  %nextx = shl i16 %x, 1
  %nexty = lshr i16 %y, 1
  %done = icmp eq i16 %nexty, 0
  br i1 %done, label %exit, label %loop
exit:
  ret i16 %nextsum
}

; Restoring division tracks overflow explicitly before word-sized subtraction,
; and compares remainders/divisors as unsigned words.
define internal i16 @nosuz16_divrem(i16 %a, i16 %b, i16 %wantrem) {
entry:
  br label %loop
loop:
  %numerator = phi i16 [%a, %entry], [%nextnum, %loop]
  %remainder = phi i16 [0, %entry], [%nextrem, %loop]
  %quotient = phi i16 [0, %entry], [%nextquot, %loop]
  %count = phi i16 [16, %entry], [%nextcount, %loop]
  %overflow = icmp slt i16 %remainder, 0
  %incoming = lshr i16 %numerator, 15
  %shiftrem = shl i16 %remainder, 1
  %candidate = or i16 %shiftrem, %incoming
  %enough = icmp uge i16 %candidate, %b
  %subtract = or i1 %overflow, %enough
  %difference = sub i16 %candidate, %b
  %nextrem = select i1 %subtract, i16 %difference, i16 %candidate
  %shiftquot = shl i16 %quotient, 1
  %quotbit = zext i1 %subtract to i16
  %nextquot = or i16 %shiftquot, %quotbit
  %nextnum = shl i16 %numerator, 1
  %nextcount = sub i16 %count, 1
  %done = icmp eq i16 %nextcount, 0
  br i1 %done, label %exit, label %loop
exit:
  %mode = icmp ne i16 %wantrem, 0
  %result = select i1 %mode, i16 %nextrem, i16 %nextquot
  ret i16 %result
}

define i16 @__udivhi3(i16 %a, i16 %b) {
  %v = call i16 @nosuz16_divrem(i16 %a, i16 %b, i16 0)
  ret i16 %v
}
define i16 @__umodhi3(i16 %a, i16 %b) {
  %v = call i16 @nosuz16_divrem(i16 %a, i16 %b, i16 1)
  ret i16 %v
}
define i16 @__divhi3(i16 %a, i16 %b) {
  %nega = icmp slt i16 %a, 0
  %negb = icmp slt i16 %b, 0
  %minus_a = sub i16 0, %a
  %minus_b = sub i16 0, %b
  %ua = select i1 %nega, i16 %minus_a, i16 %a
  %ub = select i1 %negb, i16 %minus_b, i16 %b
  %q = call i16 @__udivhi3(i16 %ua, i16 %ub)
  %negative = xor i1 %nega, %negb
  %minus_q = sub i16 0, %q
  %v = select i1 %negative, i16 %minus_q, i16 %q
  ret i16 %v
}
define i16 @__modhi3(i16 %a, i16 %b) {
  %nega = icmp slt i16 %a, 0
  %negb = icmp slt i16 %b, 0
  %minus_a = sub i16 0, %a
  %minus_b = sub i16 0, %b
  %ua = select i1 %nega, i16 %minus_a, i16 %a
  %ub = select i1 %negb, i16 %minus_b, i16 %b
  %r = call i16 @__umodhi3(i16 %ua, i16 %ub)
  %minus_r = sub i16 0, %r
  %v = select i1 %nega, i16 %minus_r, i16 %r
  ret i16 %v
}
