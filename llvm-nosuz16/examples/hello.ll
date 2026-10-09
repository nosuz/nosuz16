; Word accesses use aligned i16 byte addresses, like ordinary LLVM pointers.
target triple = "nosuz16"

declare void @llvm.nosuz16.stw(i16, i16)

define i16 @main() {
  call void @llvm.nosuz16.stw(i16 -256, i16 72) ; FF00: 'H'
  call void @llvm.nosuz16.stw(i16 -256, i16 105) ; 'i'
  call void @llvm.nosuz16.stw(i16 -256, i16 10)
  ret i16 42
}
