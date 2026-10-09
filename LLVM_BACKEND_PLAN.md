# Nosuz16 LLVM Backend Implementation Plan

Implement an experimental LLVM backend for [Nosuz16 v2.5](Nosuz16_CPU_Spec.md)
and validate its output with the [Rust emulator](nosuz16/README.md). The first
deliverable is a working compiler pipeline for a restricted set of LLVM IR
programs. The selected v2.5 memory model packs eight-bit C bytes into
16-bit physical words, using 16-bit byte-addressed pointers and 64 KiB of
unified memory.

```text
LLVM IR → Nosuz16 assembly → HEX or BIN image → Nosuz16 emulator
```

The backend implements the v2.5 instruction set, including LDB/STB. SelectionDAG handles initial
instruction selection; GlobalISel is outside the first implementation.

## Implementation status — 2026-10-10

The initial IR-to-image milestone is implemented in
[llvm-nosuz16/](llvm-nosuz16/README.md), with the LLVM source delivered as a
patch against the recorded revision. Stages 1–6 are implemented and tested;
Stage 7 includes software `i16` arithmetic, UART output, and packed byte C
memory. Clang supports ordinary memory at O0/O1/O2, fixed scalar calls,
pointers, arrays, global data, and structure fields/copies. Wider arithmetic,
aggregate calling conventions, full libc, and a public ELF/LLD ABI remain
future work.

Validation passed: twelve Clang/LLVM MC/CodeGen tests, 32 C cases with
576 guest executions plus one relocated global-pointer run, 32 IR cases at O0/O2
through assembly and direct-object paths (128 guest executions), 713 LLVM
TargetParser unit tests (four platform-specific skips), and all 36 Rust
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

## Selected C memory model — v2.5

The user selected 16-bit byte addressing with a 64 KiB unified address space.
Two C bytes occupy one physical word. `char` stays eight-bit, `sizeof(int)`
and `sizeof(void *)` stay 2, and aligned int/pointer values use one native
word in little-endian order. LLVM byte offsets and CPU addresses now agree.
The previous byte-per-word implementation and its expanded data/spill layout
are superseded; old objects must be rebuilt.

CPU v2.5 adds LDB/STB opcodes 9/A. LDB zero-extends eight bits; STB preserves
the neighboring byte. Word accesses, PC, SP, symbols, and pointers use byte
addresses. Instructions advance PC by two, and word accesses/instruction
fetch/JALR require even addresses. Relative branches retain two-byte-scaled
immediates. UART STATUS moves to FF02, while DATA remains FF00.

The memory pass emits LD/ST for aligned integer and pointer accesses and
LDB/STB for char or unaligned packed fields. Ordinary allocas, stack frames,
and globals use LLVM byte sizes directly. Memory helpers use byte operations.
Raw `nosuz16_ldw/stw` intrinsics access aligned words at byte addresses;
`nosuz16_ldb/stb` provide explicit byte access with conservative side effects.

Symbols and relocation addends remain byte-valued throughout MC and image
linking. Private ELF flag 0x205 distinguishes v2.5 objects, and old object
flags are rejected. Data sections can contain odd byte lengths; BIN preserves
them, while HEX transport explicitly zero-pads the last byte. The startup
sets sp=FF00, an even byte address below the I/O region.

The ABI retains fixed scalar calls. Integers up to 16 bits and pointers use
one native word per register/stack argument, with stack slots at sp+0, sp+2,
etc. Wider arithmetic, aggregate ABI, VLAs, atomics, and floating point remain
separate extensions. LLVM memcpy/memmove/memset use software helpers.

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
test suite grows. This configuration includes the restricted Clang
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
Describe all 20 core instructions and the N16-REF-2 HALT encoding. Emit
canonical unused fields while accepting the legal alternate encodings
specified by v2.5.

Validate immediate and register ranges. Implement the corrected MOV, CMP,
NOP, and SUBI aliases, including the MOV self-copy case, CMP scratch-register
constraints, and SUBI's -31 to 32 input range. Numeric branch operands are
two-byte-scaled offsets; label operands are byte addresses.

Resolve relative offsets from the incremented PC. At the MC/tool boundary,
handle serialized instruction sizes and addresses in bytes, scaling relative
branch offsets by two. Reject offsets that cannot be encoded without relaxation.

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
epilogues, call lowering, and return lowering. Follow the v2.5 ABI:

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
and data symbols in CPU byte addresses. Define section placement and reject
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

The packed byte memory model is selected and implemented for pointers,
arrays, structure fields, global data, and static local objects. Keep language
layout, pointer conversions, null representation, and volatile I/O consistent
when adding wider values or aggregate calling conventions.

The Clang target supports ordinary memory at O0/O1/O2 and exposes native
word I/O through `nosuz16.h`. Add ELF relocations and LLD integration for a
standard object/linking workflow; the current private object format and image
builder already support separate compilation.
Floating-point runtime support and debugging information are later extensions.

Literal `printf` calls are supported through a target IR expansion pass,
with fixed-argument UART and integer-formatting helpers. The format must
remain constant; `%s` can print a runtime character buffer. General variadic
calls and full libc formatting remain future work.

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
layers. Broader Clang C support builds on the selected memory model and
requires wider arithmetic, aggregate ABI, and runtime work.

## References

- [Nosuz16 CPU specification v2.5](Nosuz16_CPU_Spec.md)
- [Nosuz16 Rust emulator](nosuz16/README.md)
- [LLVM backend development guide](https://llvm.org/docs/WritingAnLLVMBackend.html)
- [LLVM CMake build options](https://llvm.org/docs/CMake.html)
- [LLVM language reference](https://llvm.org/docs/LangRef.html)
