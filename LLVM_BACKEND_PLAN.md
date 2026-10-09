# Nosuz16 LLVM Backend Implementation Plan

Implement an experimental LLVM backend for [Nosuz16 v2.4](Nosuz16_CPU_Spec.md)
and validate its output with the [Rust emulator](nosuz16/README.md). The first
deliverable is a working compiler pipeline for a restricted set of LLVM IR
programs. General C support follows an explicit decision about memory and
pointer representation.

```text
LLVM IR → Nosuz16 assembly → HEX or BIN image → Nosuz16 emulator
```

The CPU instruction set remains unchanged. SelectionDAG will handle initial
instruction selection; GlobalISel is outside the first implementation.

## Implementation status — 2026-10-09

The initial IR-to-image milestone is implemented in
[llvm-nosuz16/](llvm-nosuz16/README.md), with the LLVM source delivered as a
patch against the recorded revision. Stages 1–6 are implemented and tested;
Stage 7 includes software `i16` multiply/divide/remainder helpers. Wider
arithmetic, general C memory access, the long-term memory model, and a public
ELF/LLD ABI remain future work. An experimental Clang frontend now supports
optimized scalar C with word-sized function signatures and explicit word I/O;
its eight-bit `char` does not define the eventual CPU memory mapping.

Validation passed: ten Clang/LLVM MC/CodeGen tests, 15 C cases with
180 guest executions, 32 IR execution cases at O0/O2
through assembly and direct-object paths (128 guest executions), 713 LLVM
TargetParser unit tests (four platform-specific skips), and all 31 Rust
emulator tests. The example prints `Hi` and returns 42 with sp restored to
FF00h. The patch applies cleanly to the recorded baseline.

## Development baseline

Use the existing LLVM checkout at `llvm-project/`, pinned to commit
`936846286c83ae5b0dfd4c16585b41308385d650`. This checkout identifies itself as
LLVM `24.0.0git`. Create a development branch at that revision and avoid
updating the baseline during the initial implementation.

The installed tools include GCC/G++ 15.2, CMake 4.2.3, Ninja 1.13.2, LLD
21.1.8, and Python 3.14.4. The installed LLD is the host linker for building
LLVM; it does not provide Nosuz16 linking support.

Use a Release build with assertions enabled, at most two compilation jobs,
and one concurrent linking job initially. The development machine has about
7.5 GiB RAM. Reduce concurrency if the build runs out of memory.

The main repository ignores `llvm-project/`. Keep reproducible patches,
build scripts, and execution-test scripts in a tracked `llvm-nosuz16/`
directory in the main repository. Record the base revision with the patches
so another checkout can reproduce the backend. The implementation is delivered in [llvm-nosuz16/](llvm-nosuz16/README.md).

## Memory model decision

The CPU uses 16-bit word addresses. LLVM represents storage sizes and pointer
offsets using eight-bit bytes, and this checkout's Clang fixes `char` width
and alignment at eight bits. These assumptions are visible in
`llvm/include/llvm/IR/DataLayout.h` and
`clang/include/clang/Basic/TargetInfo.h`.

A target DataLayout string alone cannot turn LLVM bytes into CPU words.
Changing pointer width also does not solve the difference in address units.
Do not apply a general rule that divides every pointer offset by two: odd
byte offsets, packed objects, and byte accesses require their own semantics.

The initial backend will compile register arithmetic, control flow, calls,
compiler-generated stack accesses, and explicit word-memory operations.
Word-memory operations will take a 16-bit integer word address, using target
intrinsics rather than ordinary LLVM pointer arithmetic. Initially, preserve
their ordering conservatively, including I/O accesses. Declare their memory
effects accurately; a read discarded by its caller can still consume UART
input and must not be removed.

Compiler-generated stack layout still uses LLVM's byte-based offsets. Require
word-aligned slots and translate those offsets explicitly when producing
machine addresses. Generic IR loads, stores, GEP operations, and general
pointer conversions remain unsupported until their mapping is defined.

Choose one long-term model before starting general Clang integration:

| Model | Consequences |
| --- | --- |
| Native word addressing | Preserve the proposed 16-bit char and word-pointer C model. Requires custom frontend integration and an audit of LLVM memory assumptions beyond ordinary target configuration. |
| Emulated byte addressing | Keep ordinary Clang eight-bit chars. Implement byte extraction and read-modify-write stores. Covering 64K CPU words requires at least 17 bits of byte address, likely using 32-bit C pointers and a separate language ABI. |

The choice remains open. Early arithmetic, encoding, and register-allocation
work can proceed independently. Neither model changes the physical CPU ISA.

## Initial scope

Support `i16` values, constants, integer arithmetic and logic, comparisons,
branches, returns, ordinary fixed-argument calls, register spills, and
explicit word-memory access. Handle boolean results in registers through
legalization to the supported machine representation.

Unsupported operations must produce clear diagnostics. The first release
does not claim general C compatibility or support for floating point,
atomics, exceptions, variadic functions, arbitrary aggregates, debugging
information, or dynamic linking. Wider arithmetic is added after the core
pipeline and calling convention work.

## Stage 1 Reproducible build setup

Create the development branch, tracked patch workflow, and build/test scripts.
Use the existing MSP430 backend as an API reference for a small 16-bit
SelectionDAG target, while deriving Nosuz16 semantics from its own spec.

Configure only the required targets and tools. Once the Nosuz16 target
skeleton exists, the intended configuration is:

```sh
cmake -S llvm-project/llvm -B llvm-project/build-nosuz16 -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLVM_ENABLE_ASSERTIONS=ON \
  -DLLVM_USE_LINKER=lld \
  -DLLVM_PARALLEL_LINK_JOBS=1 \
  -DLLVM_TARGETS_TO_BUILD="" \
  -DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=Nosuz16 \
  -DLLVM_ENABLE_PROJECTS=clang \
  -DCLANG_ENABLE_STATIC_ANALYZER=OFF \
  -DCLANG_ENABLE_ARCMT=OFF \
  -DLLVM_INCLUDE_TESTS=ON

cmake --build llvm-project/build-nosuz16 --parallel 2 \
  --target clang llc llvm-mc llvm-objdump llvm-tblgen FileCheck count not \
    llvm-config llvm-readobj opt TargetParserTests
```

The experimental-target option requires the target to have been registered;
apply the tracked patch before using this configuration. Build further tools required by individual tests as the
test suite grows. This configuration includes the restricted scalar Clang
frontend; Nosuz16 LLD integration remains future work.

**Completion:** a clean build from the recorded baseline and patches is
reproducible without changing system packages.

## Stage 2 Target registration and descriptions

Create `llvm/lib/Target/Nosuz16/` with target registration, CMake integration,
TargetMachine and subtarget classes, and TableGen descriptions for registers,
instructions, and calling conventions. Add target-triple support as needed
for the chosen tool interface.

Describe r0 as constant zero and exclude it from allocation. Reserve r6 as
the stack pointer and initially reserve r7 as the link register. Allocate
r1-r5 according to the ABI. The first implementation reserves r5 as the
long-branch scratch register and allocates r1-r4; branch-using functions
preserve incoming r5. Model architectural flags as implicit instruction
inputs and outputs where appropriate.

**Completion:** `llc --version` lists Nosuz16 and the generated target tables
build successfully.

## Stage 3 Instruction encoding and assembly

Implement MC instruction printing, parsing, encoding, decoding, and fixups.
Describe all 18 core instructions and the N16-REF-1 HALT encoding. Emit
canonical unused fields while accepting the legal alternate encodings
specified by v2.4.

Validate immediate and register ranges. Implement the corrected MOV, CMP,
NOP, and SUBI aliases, including the MOV self-copy case, CMP scratch-register
constraints, and SUBI's -31 to 32 input range. Numeric branch operands are
word offsets; label operands are target addresses.

Resolve relative offsets from the incremented PC. At the MC/tool boundary,
handle serialized instruction sizes in bytes and architectural offsets in
words explicitly. Reject offsets that cannot be encoded without relaxation.

**Completion:** encoding and decoding tests cover every instruction, signed
immediate boundaries, PC-relative offsets, reserved encodings, and alias
constraints. Expected instruction words agree with the emulator.

## Stage 4 Basic instruction selection

Implement SelectionDAG lowering and instruction selection for `i16`
arithmetic, bitwise operations, shifts, comparisons, branches, and returns.
Describe two-operand ALU instructions with tied input/output operands.
Register copies must work when the source and destination overlap and must
declare their flag effects.

Materialize arbitrary 16-bit constants using legal instruction sequences.
Implement variable shifts using repeated one-bit shifts. Lower signed
comparisons to the register-comparison branches and expand unsigned
comparisons into a correct sequence. Avoid introducing fictitious native
MOV, CMP, multiply, or variable-shift instructions.

Preserve flag dependencies, especially ADDC/SUBC carry chains. Test that
scheduling and instruction expansion cannot insert flag-clobbering copies
into those chains.

**Completion:** small IR functions compile and execute correctly, including
constants, overlapping operands, signed and unsigned comparisons, shifts,
and loops. Unsupported IR receives a diagnostic rather than invalid code.

## Stage 5 Stack frames and calling convention

Implement copies, spills, reloads, frame-index elimination, prologues,
epilogues, call lowering, and return lowering. Follow the v2.4 ABI:

- r1-r3 carry the first three word arguments.
- Additional word arguments occupy the caller's stack and are cleaned up by
  the caller.
- r1 carries a 16-bit return value; later 32-bit returns use r1/r2.
- r4/r5 are callee-saved; r6 is restored on return.
- Non-leaf functions save and restore their incoming r7.
- Flags are caller-saved.

Handle frames and stack adjustments exceeding the signed six-bit immediate
range. Large offsets need address construction and legal scratch-register
management, including when all allocatable registers are occupied.

**Completion:** tests with nested calls, more than three arguments,
callee-saved registers, large stack offsets, and forced spills execute
correctly and restore the stack pointer.

## Stage 6 Memory and executable images

Lower explicit word-memory intrinsics to LD/ST while preserving the required
side effects. Add a startup sequence that sets sp to FF00h, calls the entry
function, and executes HALT when that function returns. CPU reset itself
must continue to leave sp at zero.

Provide a flat-image assembly and symbol-resolution path, backed by LLVM MC,
that emits the emulator's HEX and little-endian BIN formats. Resolve code
and data symbols in CPU word addresses. Define section placement and reject
images that overlap reserved I/O or exceed the address space.

The first implementation uses fixed-size long branch/call sequences after
pseudo-instruction expansion. Invert conditions where necessary, materialize
absolute target addresses, and use JALR. This supports destinations beyond
JAL's range with stable layout; iterative relaxation to smaller sequences is
a later size optimization.

A public ELF ABI, standardized relocations, and LLD support are deferred.
LLVM MC currently uses private ELF32/EM_NONE transport objects consumed only
by the flat-image tool; these are not a public object-file format. A flat-image
tool is required to close the first execution pipeline; assembly output
alone is not the milestone.

**Completion:** complete images exercise calls, loops, word-memory access,
and UART output in the Rust emulator. Out-of-range offsets, invalid images,
and execution-limit failures are reported correctly.

## Stage 7 Runtime and language integration

Add runtime helpers for multiplication, division, remainder, and wider
integer operations. Extend legalization and define the ABI for any additional
multiword argument types. Test carry and borrow chains used by wider values.

Resolve the long-term memory model before implementing general pointers,
arrays, structures, memory intrinsics, or general Clang memory access. Define the
language data model, object layout, pointer conversions, null pointer
representation, and volatile I/O rules consistently.

The scalar Clang target is implemented independently of that decision. It
requires frontend optimization (O1/O2) to eliminate ordinary local loads and
stores, and exposes word I/O through `nosuz16.h`. Expand this subset after
choosing the memory model. Add ELF relocations and LLD integration for a
standard object/linking workflow; the current private object format and image
builder already support separate compilation.
Floating-point runtime support and debugging information are later extensions.

Literal `printf` calls are supported through a target IR expansion pass,
with fixed-argument UART and integer-formatting helpers. Constant format and
`%s` strings avoid a general pointer or variadic ABI; dynamic strings and
full libc formatting remain future work.

**Completion:** the supported language and ABI are documented, and compiled
C programs pass execution tests without relying on host data-layout defaults.

## Validation strategy

Use three complementary forms of validation:

| Test layer | Checks |
| --- | --- |
| LLVM CodeGen tests | Selection, register constraints, stack frames, flag dependencies, and diagnostics |
| LLVM MC tests | Instruction words, parsing, decoding, fixups, aliases, and range errors |
| Emulator execution tests | Returned values, registers, PC, flags, memory effects, ABI preservation, and UART output |

Use the existing emulator tests as ISA regression coverage. Compare supported
compiled programs with independently calculated results and guest-observable
memory/output. Use a bounded execution limit to detect faulty branches or
returns. Run backend tests at both unoptimized and optimized code-generation
settings before claiming support for a feature.

The first implementation is complete when a clean build can compile the
documented IR subset, produce executable images, and pass all three test
layers. General Clang C support is a separate milestone and depends on the
memory-model decision.

## References

- [Nosuz16 CPU specification v2.4](Nosuz16_CPU_Spec.md)
- [Nosuz16 Rust emulator](nosuz16/README.md)
- [LLVM backend development guide](https://llvm.org/docs/WritingAnLLVMBackend.html)
- [LLVM CMake build options](https://llvm.org/docs/CMake.html)
- [LLVM language reference](https://llvm.org/docs/LangRef.html)
