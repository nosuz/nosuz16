# Experimental Nosuz16 LLVM backend

This backend targets [Nosuz16 v2.4](../Nosuz16_CPU_Spec.md) through
SelectionDAG and LLVM MC. It compiles a restricted LLVM IR subset to runnable
word-addressed HEX/BIN images. Clang C support requires the memory-model
choice discussed in the [implementation plan](../LLVM_BACKEND_PLAN.md).

## Repository storage

Commit this directory in the main repository. It contains the complete backend
patch, baseline revision, runtime, scripts, examples, and execution tests.
`llvm-project/` is an ignored working checkout used to build LLVM; its files
and build products are not included in the main repository's commits.

On another machine, check out LLVM at the revision in `LLVM_BASE_REVISION`,
then run `scripts/apply.sh` and `scripts/build.sh` as shown below. The patch
contains all added backend source files and all changes to existing LLVM files.

## Build and run

Use the installed LLVM checkout at the revision recorded in
[LLVM_BASE_REVISION](LLVM_BASE_REVISION). No package-installation command is
run by these scripts. The host build needs GCC/G++, CMake, Ninja, LLD, Python
3, zlib/zstd development libraries, and Rust/Cargo for execution tests.

```sh
./llvm-nosuz16/scripts/apply.sh
./llvm-nosuz16/scripts/build.sh
./llvm-nosuz16/scripts/compile.sh llvm-nosuz16/examples/hello.ll /tmp/hello.hex
cargo run --manifest-path nosuz16/Cargo.toml -- --dump /tmp/hello.hex
python3 llvm-nosuz16/tests/run.py
```

The example prints `Hi` followed by a newline and returns 42 in r1. The
startup code initializes sp to FF00h, calls `main`, and halts on return.
The CPU's reset behavior still leaves sp at zero. The supplied startup
expects `main` to take no arguments and return an `i16` or void.

`LLVM_SOURCE_DIR` and `LLVM_BUILD_DIR` override the checkout/build locations.
`LLVM_BUILD_JOBS` defaults to two; linking uses one job. Build products stay
inside the ignored LLVM checkout. The backend source and LLVM regression
tests are carried in [the patch](patches/0001-nosuz16-backend.patch).

## Supported IR and ABI

Functions use the ordinary LLVM `ccc` with fixed `i16` arguments and either
an `i16` or void return. The first three arguments use r1-r3; remaining
arguments occupy consecutive words at the caller's sp. The caller reserves
and releases outgoing argument space. The outgoing stack argument area is
limited to 32766 LLVM bytes (16383 CPU words). Returns use r1. r4/r5 and sp are
preserved; functions that overwrite r7 save their incoming link register.
Flags are caller-saved.

The allocator uses r1-r4. r0, sp/r6, and lr/r7 are reserved; r5 is reserved
for long branches. A branch-using function saves r5 as required by the ABI.
Compiler stack-slot sizes/offsets are measured in LLVM bytes, checked for
word alignment, and explicitly translated to CPU word offsets. Large stack
accesses temporarily adjust sp and restore it around the access, so they
work without an additional free scratch register.

Implemented operations include constants, add/subtract, bitwise logic,
signed/unsigned comparisons, boolean intermediates, select, shifts, branches,
loops, calls, returns, and register spills. Constant shifts emit native
one-bit shifts; variable shifts use loops. Defined `i16` shift counts are
0 through 15. `i1`/`i8` intermediates are legalized; function arguments and
returns remain word-sized.

Multiplication, signed/unsigned division, and remainder call software
helpers in [runtime/arithmetic.ll](runtime/arithmetic.ll). `compile.sh`
links those helpers automatically. Direct `llc` users must link the runtime
when their IR needs it. Division by zero and signed INT_MIN/-1 have LLVM's
undefined semantics. Wider operations, floating point, aggregates, atomics,
exceptions, variadic/indirect calls, and general pointers are outside this
release. Unsupported IR produces an error.

### Word memory and I/O

Ordinary LLVM pointer loads/stores, GEP, alloca, and pointer conversions are
rejected. The target DataLayout does not redefine LLVM's byte unit. Instead,
these intrinsics use an integer CPU **word address**:

```llvm
declare i16 @llvm.nosuz16.ldw(i16)
declare void @llvm.nosuz16.stw(i16, i16)

; Read one word; address FF00h consumes a queued UART byte.
%byte = call i16 @llvm.nosuz16.ldw(i16 -256)
; Address first, value second. FF00h transmits the value's low byte.
call void @llvm.nosuz16.stw(i16 -256, i16 65)
```

Both intrinsics conservatively have unknown memory effects and explicit side
effects. Optimizers must retain discarded reads and preserve I/O ordering.
This deliberately favors correctness over memory optimizations.

## Assembly and images

`llvm-mc -triple=nosuz16` parses/encodes the full v2.4 instruction set,
including HALT and the corrected MOV, CMP, SUBI, and NOP aliases.
`llvm-mc -triple=nosuz16 --disassemble` decodes native words. CMP syntax is
`cmp rs1, rs2, tmp`; tmp must differ from r0 and both inputs.

Native branch/jump numeric operands are signed word displacements relative
to the next PC. Label operands resolve to target locations. Out-of-range
native branches are rejected. Compiler output instead uses `brcc`, `ljmp`,
and `lcall` pseudos that materialize absolute word addresses and use JALR.
These fixed-size long sequences support all destinations in the address
space without iterative relaxation. Constant loads currently always use a
33-word construction; branch and constant-size optimization is future work.
`ljmp`/`brcc` clobber r5 and flags; `lcall` clobbers r7 and flags. `li` also
changes flags. These pseudos must be accounted for when writing assembly.

The image tool uses **private ELF32/EM_NONE transport objects** emitted by
LLVM MC. Their four private relocation kinds are PC6, PC9, a relocated LI
sequence, and a word-valued symbol reference. This is an implementation
transport between MC and the image builder, without a public ELF machine
number, stable object ABI, or LLD support. Do not pass these objects to a
system linker. MC section offsets and symbol addends use serialized byte
units; final architectural addresses and displacements use words.

```sh
llvm-project/build-nosuz16/bin/llc -mtriple=nosuz16 -verify-machineinstrs \
  llvm-nosuz16/examples/hello.ll -o /tmp/hello.s
llvm-project/build-nosuz16/bin/llvm-mc -triple=nosuz16 -filetype=obj \
  /tmp/hello.s -o /tmp/hello.o
llvm-project/build-nosuz16/bin/llvm-mc -triple=nosuz16 -filetype=obj \
  llvm-nosuz16/runtime/start.s -o /tmp/start.o
python3 llvm-nosuz16/scripts/image.py /tmp/start.o /tmp/hello.o -o /tmp/hello.bin
```

Executable sections precede data sections. Input order determines ordering
within each group, so put startup first. Allocated sections contain aligned
words; BSS is zero-filled. HEX contains one 16-bit word per line; BIN is
little-endian. The image builder rejects unresolved/duplicate symbols,
unaligned or oversized sections, range errors, and images reaching FF00h.
It does not dynamically detect a stack colliding with the image; the caller
must ensure sufficient RAM below FF00h for its program's call depth.

`image.py --origin 0x100` places an image at that **word** address. Run it
with the emulator's matching `--load-address 0x100`. Startup and relocated
calls are resolved for the selected origin.

## Verification

The patch includes LLVM MC and CodeGen regression tests. Run them with:

```sh
llvm-project/build-nosuz16/bin/llvm-lit -v \
  llvm-project/llvm/test/MC/Nosuz16 \
  llvm-project/llvm/test/CodeGen/Nosuz16
llvm-project/build-nosuz16/unittests/TargetParser/TargetParserTests
```

[tests/run.py](tests/run.py) checks independently specified native words,
aliases, illegal encodings/operands, and actual guest results. Each execution
case runs at O0 and O2, both through assembly round trips and direct LLVM
object emission, with a bounded instruction limit. Startup seeds r4/r5 with
sentinels and checks callee preservation and restored sp. The suite also
runs the emulator's existing Rust tests.

Verified against the pinned LLVM checkout: six MC/CodeGen tests; 32 execution
cases with 128 guest runs; 713 TargetParser tests passed with four host-platform
skips; and all 31 emulator tests passed. The standalone build/compile scripts
also produced and ran the `Hi` example successfully.
