# Experimental Nosuz16 LLVM backend

This backend targets [Nosuz16 v2.5](../Nosuz16_CPU_Spec.md) through
SelectionDAG and LLVM MC. It compiles a restricted LLVM IR subset to runnable
byte-addressed HEX/BIN images. Clang supports freestanding C with ordinary
loads/stores, pointers, arrays, structures, and globals using packed eight-bit
bytes. Wider arithmetic and the full C library remain outside this subset.

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

## Docker SDK

The [.devcontainer/Dockerfile](../.devcontainer/Dockerfile) has three stages. `builder` fetches the
revision in `LLVM_BASE_REVISION`, applies the backend patch, builds LLVM/Clang,
and installs selected components. `emulator-builder` builds and tests the Rust emulator.
The final `dev` stage contains the tools for developing Nosuz16 programs:

| Command | Purpose |
| --- | --- |
| `nosuz16-cc INPUT.c OUTPUT.hex\|OUTPUT.bin` | Compile C and link the supplied runtime into an image |
| `nosuz16-ir INPUT.ll OUTPUT.hex\|OUTPUT.bin` | Compile LLVM IR and link an image |
| `nosuz16` | Run an image in the emulator |
| `clang`, `llc`, `llvm-mc` | Compile C/IR and assemble native objects |
| `opt` | Optimize LLVM IR |
| `llvm-objdump`, `llvm-readobj` | Inspect/disassemble private transport objects |

Clang's built-in headers, shared `libLLVM`, the Nosuz16 header, runtime
sources, image builder, and examples are installed under `/opt/nosuz16`.
`LLVM_BUILD_DIR` points to the installed toolchain and its binaries are on
`PATH`. Bash, Python, and Make are available. The final image contains no
LLVM checkout, backend patch, static LLVM archives, CMake/Ninja, Rust/Cargo,
or LLVM backend development/test utilities. Existing Git/SSH, uv/Python, Node.js,
Codex, Claude, Japanese locale, Tokyo timezone, and the `ubuntu` user are
retained. Rebuild the VS Code development container to use these installed
tools; the existing workspace mount and post-create setup continue to work.
LLVM backend and emulator source development require their respective build
stages or a separate environment with the corresponding build dependencies.

From the repository root:

```sh
docker build -f .devcontainer/Dockerfile -t nosuz16-dev .
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/workspaces" nosuz16-dev \
  nosuz16-cc llvm-nosuz16/examples/hello.c hello.bin
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/workspaces" nosuz16-dev \
  nosuz16 --dump hello.bin
docker run --rm -it --user "$(id -u):$(id -g)" -v "$PWD:/workspaces" nosuz16-dev
```

The mount supplies your program sources and receives generated images.
The default working directory is `/workspaces`. The compiler remains freestanding;
the SDK does not add a complete C library or system linker for Nosuz16.
For manual disassembly, specify `llvm-objdump --triple=nosuz16 -d PROGRAM.o`.

`.dockerignore` excludes the local LLVM checkout, Cargo build directories,
and agent/Git data from the build context. LLVM compilation defaults to two
jobs and one link job; `--build-arg LLVM_BUILD_JOBS=N` changes compilation
parallelism. The `emulator-builder` stage uses Rust 1.85.1. Package installation occurs
inside Docker stages; no host package installation is needed.

The final stage runs [tests/sdk.py](tests/sdk.py) against the installed tools.
It checks C/IR images, UART input/output, stack restoration, relocated Clang
resource headers, packed memory, optimization, and object inspection. Run
that check again with:

```sh
docker run --rm nosuz16-dev python3 /opt/nosuz16/llvm-nosuz16/tests/sdk.py
```

## Mandelbrot ASCII demo

[examples/mandelbrot.c](examples/mandelbrot.c) renders the 79×25
[ASCIIART benchmark](https://haserin09.la.coocan.jp/asciiart.html) through
UART. It samples `x * 0.0458` for `x=-39..39` and `y * 0.08333` for
`y=-12..12`, starts each orbit at its sample coordinate, and performs up to
16 updates. Escaping points show the update index in hexadecimal (`0`–`F`);
bounded points are spaces. See [sample output](examples/mandelbrot.txt).

The calculation uses Q16 fixed point stored as two 16-bit fields. Carry,
borrow, and partial-product helpers avoid unsupported C `long` and floating
point arithmetic. Coordinates are rounded separately to avoid accumulated
step error. For this grid, the emulator's entire output matches an independent
double-precision implementation of the benchmark formula.

Every one of the 1,975 pixels runs its own orbit calculation. Pixel results
are emitted immediately without caching, mirroring rows, or analytic
interior shortcuts. Arithmetic improvements reuse squares between orbit
updates, use three partial products for squaring, and replace small integer
cross-products with additions. These changes preserve every output byte,
including the hexadecimal escape counts.

With the current SDK at `-O2`, execution drops from 405,148,656 to
133,882,384 guest instructions (including HALT), about **3.0× faster** by
instruction count. The binary grows from 20,936 to 23,988 bytes. These
measurements cover the entire program, including UART output; emulator
wall time depends on the host, and hardware timing depends on instruction
costs.

Inside the development container, use the source in the mounted workspace
so a demo added after the image was built is available immediately:

```sh
nosuz16-cc /workspaces/llvm-nosuz16/examples/mandelbrot.c /tmp/mandelbrot.bin
nosuz16 /tmp/mandelbrot.bin
```

From a source checkout with the compiler built:

```sh
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/mandelbrot.c /tmp/mandelbrot.bin
cargo run --release --manifest-path nosuz16/Cargo.toml -- \
  /tmp/mandelbrot.bin
```

The emulator runs without a step limit by default; use `--max-steps COUNT`
to bound a run. The demo returns zero and emits 25 rows of 79 ASCII
characters, each with a newline.

Run `python3 llvm-nosuz16/tests/mandelbrot.py` to compare every pixel and the
saved sample with an independent floating-point reference. It uses the
installed emulator, the local release build, or `NOSUZ16_EMULATOR` if set.
The test also requires completion within 200 million guest instructions.

## Clang C frontend

The build includes `clang` with a Nosuz16 target. Compile freestanding C at
`-O0`, `-O1`, or `-O2`, including arithmetic, comparisons, loops, fixed-argument
calls, pointers, addressable local variables, arrays, globals, and structure
fields. Supported scalar arguments and returns are integers up to 16 bits
and 16-bit pointers; structures passed or returned by value remain unsupported.

```sh
export PATH="/workspaces/llvm-project/build-nosuz16/bin:$PATH"
clang --target=nosuz16 -ffreestanding -fno-builtin -O2 \
  -I llvm-nosuz16/include -S llvm-nosuz16/examples/hello.c -o /tmp/hello.s
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/hello.c /tmp/hello.hex
cargo run --manifest-path nosuz16/Cargo.toml -- --dump /tmp/hello.hex
python3 llvm-nosuz16/tests/clang.py
```

`clang -c` also emits the private MC object format. Use the image builder to
link these objects with startup and runtime; system linkers and Clang's
ordinary executable-linking step do not support Nosuz16.

### C memory model

Nosuz16 v2.5 has 16-bit byte addresses and 64 KiB of unified memory.
Characters are packed: `sizeof(char)` is 1, while `sizeof(int)` and
`sizeof(void *)` are 2. An aligned int or stored pointer uses one physical
16-bit word. Memory is little-endian; `0x1234` occupies bytes `34 12`.

C pointer values match CPU byte addresses. `char *p + 1` advances one byte,
and `int *p + 1` advances two. Character stores use STB and preserve the
neighboring byte. LDB zero-extends; signed char conversions sign-extend.
Aligned integer/pointer accesses use LD/ST. Packed structure fields at odd
addresses use two LDB/STB operations and shifts. Alignment faults protect
native word operations and instruction fetches at odd addresses.

`__NOSUZ16_BYTE_ADDRESSABLE__` and `__NOSUZ16_SPEC_VERSION__ == 205`
identify this model. The old `__NOSUZ16_BYTE_PER_WORD__` macro is absent.
The older `__NOSUZ16_SCALAR_C__` macro remains for compatibility.

Stack objects, register spills, globals, and ABI slots use normal packed
byte layouts. Calls require sp aligned to two bytes. LLVM memcpy, memmove,
and memset use [runtime/memory.c](runtime/memory.c), linked automatically by
`compile.sh`. Rebuild all v2.4 objects: address units, stack offsets, global
layout, and relocations changed. The image builder rejects objects without
the private v2.5 ELF flag.

Dynamic stack allocation/VLAs, stack alignment above two C bytes, aggregate
arguments/returns, wider scalar memory values/arithmetic, floating point,
atomics, exceptions, indirect calls, and user-defined variadic functions
remain unsupported. System headers and a full libc are not supplied.

Try a line buffer with runtime `%s` output:

```sh
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/read-line.c /tmp/line.hex
cargo run --manifest-path nosuz16/Cargo.toml -- \
  --uart-input $'Hello\n' --dump /tmp/line.hex
```

This prints `You typed: Hello` followed by a newline and returns 17.

Include [include/nosuz16.h](include/nosuz16.h) for explicit word-memory I/O:

```c
#include "nosuz16.h"
int main(void) {
  nosuz16_stw(NOSUZ16_UART_TXRX, 'A');
  return nosuz16_ldw(NOSUZ16_UART_STATUS);
}
```

These functions map to LLVM word/byte memory intrinsics. Their
addresses are CPU byte addresses, and unused reads remain observable.
The header does not require a libc or a sysroot.

### UART character functions

The same header declares `int getc(void)` and `int putc(int c)`, implemented
in [runtime/console.c](runtime/console.c). These are bare-metal UART functions
with no `FILE` argument. `getc()` polls RX_READY, consumes one byte, and returns
0–255, including NUL. It waits indefinitely when no input is available; there
is no EOF. `putc(c)` polls TX_READY, sends the low eight bits of `c`, and
returns that byte as an `int`.

Both `compile-c.sh` and `compile.sh` link this runtime automatically. For
manual object linking, compile `runtime/console.c` with the same target,
freestanding flags, include directory, and `-O2`, then pass its object to
`image.py` alongside your program, startup, arithmetic, and memory runtimes.

```c
#include "nosuz16.h"
int main(void) {
  return putc(getc());
}
```

Try [examples/echo.c](examples/echo.c):

```sh
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/echo.c /tmp/echo.hex
cargo run --manifest-path nosuz16/Cargo.toml -- \
  --uart-input A --dump /tmp/echo.hex
```

### Formatted UART output

`nosuz16.h` also declares `int printf(const char *format, ...)`. Supported
conversions are `%d`, `%i`, `%u`, `%x`, `%X`, `%o`, `%c`, `%s`, and `%%`.
Integer arguments use the 16-bit C `int`/`unsigned int` types. The format
must resolve to a constant string; `%s` also supports runtime character buffers. `%c` sends the low
eight bits, including NUL; `%s` stops at the first NUL. The return value is
the number of UART bytes written; use messages that fit a signed 16-bit count.

```c
#include "nosuz16.h"
int main(void) {
  return printf("Hello %s! value=%d hex=%X %%\n", "Nosuz16", -123, 0xbeefu);
}
```

```sh
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/printf.c /tmp/printf.hex
cargo run --manifest-path nosuz16/Cargo.toml -- --dump /tmp/printf.hex
```

This prints `Hello Nosuz16! value=-123 hex=BEEF %` followed by a newline
and returns 37. The backend expands literal `printf` calls into fixed-argument
calls to `putc` and number-formatting helpers in `runtime/console.c`. These
helpers are linked automatically by the image compiler. Direct Clang object
users should link the console, memory, and arithmetic runtimes through `image.py`.
There is no standalone variadic `printf` ABI or function-pointer entry point.
Dynamic format strings, width, precision, flags, length modifiers, floating-point
conversions, and other specifiers produce a compiler diagnostic. User-defined
variadic functions remain unsupported.

## Supported IR and ABI

Functions use the ordinary LLVM `ccc` with fixed scalar integer/pointer
arguments and a scalar or void return. Scalar values occupy one native word
in the call ABI, regardless of their C memory representation. The first three arguments use r1-r3; remaining
arguments occupy consecutive words at the caller's sp. The caller reserves
and releases outgoing argument space. The outgoing stack argument area is
limited to 32766 LLVM bytes (16383 CPU words). Returns use r1. r4/r5 and sp are
preserved; functions that overwrite r7 save their incoming link register.
Flags are caller-saved. Incoming sp must be an even CPU byte address.

The allocator uses r1-r4. r0, sp/r6, and lr/r7 are reserved; r5 is reserved
for long branches. A branch-using function saves r5 as required by the ABI.
Compiler stack-slot sizes/offsets use bytes directly. Native word slots
require two-byte alignment; char object addresses may be odd. Large stack
accesses temporarily adjust sp and restore it around the access, so they
work without an additional free scratch register.

Implemented operations include constants, add/subtract, bitwise logic,
signed/unsigned comparisons, boolean intermediates, select, shifts, branches,
loops, calls, returns, and register spills. Constant shifts emit native
one-bit shifts; variable shifts use loops. Defined `i16` shift counts are
0 through 15. `i1`/`i8` values are legalized; function arguments and
returns occupy native words.

Multiplication, signed/unsigned division, and remainder call software
helpers in [runtime/arithmetic.ll](runtime/arithmetic.ll). `compile.sh`
links those helpers automatically. Direct `llc` users must link the runtime
when their IR needs it. Division by zero and signed INT_MIN/-1 have LLVM's
undefined semantics. Wider operations, floating point, aggregate values/ABI, atomics,
exceptions, and variadic/indirect calls are outside this release. Unsupported IR produces an error.

### Word memory and I/O

Ordinary pointer memory accesses use the packed byte representation above.
For full native words, including memory-mapped I/O, these intrinsics use an
integer CPU **byte address**:

```llvm
declare i16 @llvm.nosuz16.ldw(i16)
declare void @llvm.nosuz16.stw(i16, i16)

; Read one word; address FF00h consumes a queued UART byte.
%byte = call i16 @llvm.nosuz16.ldw(i16 -256)
; Address first, value second. FF00h transmits the value's low byte.
call void @llvm.nosuz16.stw(i16 -256, i16 65)
```

Both word intrinsics and the byte intrinsics `llvm.nosuz16.ldb/stb` conservatively have unknown memory effects and explicit side
effects. Optimizers must retain discarded reads and preserve I/O ordering.
This deliberately favors correctness over memory optimizations.

## Assembly and images

`llvm-mc -triple=nosuz16` parses/encodes the full v2.5 instruction set,
including HALT and the corrected MOV, CMP, SUBI, and NOP aliases.
`llvm-mc -triple=nosuz16 --disassemble` decodes native words. CMP syntax is
`cmp rs1, rs2, tmp`; tmp must differ from r0 and both inputs.

Native branch/jump numeric operands are signed two-byte-scaled displacements relative
to the next PC. Label operands resolve to target locations. Out-of-range
native branches are rejected. Compiler output instead uses `brcc`, `ljmp`,
and `lcall` pseudos that materialize absolute byte addresses and use JALR.
These fixed-size long sequences support all destinations in the address
space without iterative relaxation. Constant loads currently always use a
33-word construction; branch and constant-size optimization is future work.
`ljmp`/`brcc` clobber r5 and flags; `lcall` clobbers r7 and flags. `li` also
changes flags. These pseudos must be accounted for when writing assembly.

The image tool uses **private ELF32/EM_NONE transport objects** emitted by
LLVM MC. They carry private ELF flag `0x205`; their five relocation kinds are
PC6, PC9, a relocated LI sequence for data, a relocated LI sequence for aligned
control targets, and a 16-bit byte-addressed symbol reference. This is an implementation
transport between MC and the image builder, without a public ELF machine
number, stable object ABI, or LLD support. Do not pass these objects to a
system linker. MC section offsets and symbol addends use serialized byte
units; architectural addresses use bytes; relative branches encode two-byte units.

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
within each group, so put startup first. Executable sections require aligned instructions; data sections may contain
individual bytes. BSS is zero-filled. HEX contains one 16-bit word per line
and explicitly zero-pads a trailing byte; BIN preserves odd byte lengths. The image builder rejects unresolved/duplicate symbols,
unaligned or oversized sections, range errors, and images reaching FF00h.
It does not dynamically detect a stack colliding with the image; the caller
must ensure sufficient RAM below FF00h for its program's call depth.

`image.py --origin 0x100` places an image at that **byte** address. Run it
with the emulator's matching `--load-address 0x100`. Startup and relocated
calls are resolved for the selected origin.

## Verification

The patch includes LLVM MC and CodeGen regression tests. Run them with:

```sh
llvm-project/build-nosuz16/bin/llvm-lit -v \
  llvm-project/llvm/test/MC/Nosuz16 \
  llvm-project/llvm/test/CodeGen/Nosuz16 \
  llvm-project/clang/test/Preprocessor/init-nosuz16.c \
  llvm-project/clang/test/CodeGen/Nosuz16
python3 llvm-nosuz16/tests/clang.py
llvm-project/build-nosuz16/unittests/TargetParser/TargetParserTests
```

[tests/run.py](tests/run.py) checks independently specified native words,
aliases, illegal encodings/operands, and actual guest results. Each execution
case runs at O0 and O2, both through assembly round trips and direct LLVM
object emission, with a bounded instruction limit. Startup seeds r4/r5 with
sentinels and checks callee preservation and restored sp. The suite also
runs the emulator's existing Rust tests.

Verified against the pinned LLVM checkout: twelve Clang/MC/CodeGen tests;
32 IR cases with 128 guest runs; 32 C cases with 576 guest runs plus
a relocated global-pointer run;
713 TargetParser tests passed with four host-platform skips; and all 36
emulator tests passed. Both IR and C compile scripts produced and ran the
`Hi` example successfully. C execution covers frontend O0/O1/O2, LLVM codegen
O0/O2, direct Clang assembly/object emission, software arithmetic, calls with
70 arguments, full-register signed-character ABI checks, observable UART reads,
packed byte/int/pointer storage, high addresses,
array and structure access/copy, packed layouts, stack alignment, memory
intrinsics, and runtime `%s` buffers. An empty UART input checks that `getc`
keeps waiting. Unsupported C cases are checked for diagnostics.
