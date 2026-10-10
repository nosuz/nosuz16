# Nosuz16 Rust emulator

A dependency-free Rust library and command-line emulator for
[Nosuz16 CPU specification v2.5](../Nosuz16_CPU_Spec.md). Implements all
20 core instructions, 64 KiB of unified memory, the zero register, flags,
and memory-mapped UART I/O. No cycle-accurate timing or graphical video device
is modeled.

## Run

Requires Rust 1.85 or later and a native linker.

```sh
cd nosuz16
cargo run --release -- examples/hello.hex
# Output: Hi

cargo run -- --trace --dump examples/hello.hex
cargo run -- --load-address 0x100 --entry 0x100 program.hex
cargo run -- --format bin --uart-input "hello" program.bin
cargo test
cargo clippy --all-targets -- -D warnings
```

Use `--help` for options. UART bytes go to stdout; trace, final state, and
errors go to stderr. Successful HALT returns exit status 0. Illegal
instructions, alignment faults, invalid images, and instruction-limit exhaustion return a
nonzero status. Execution is unlimited unless `--max-steps COUNT` is supplied.
An explicit limit counts every instruction, including HALT.

UART input always comes from stdin, including interactive games. Terminal
input normally arrives after pressing Enter; piped input also works. Any
`--uart-input` bytes are queued first, followed by bytes read from stdin.
Closing stdin stops the host reader but does not halt the emulated CPU or
send an EOF byte to the UART. Interactive programs should provide a quit
command (the Othello demo uses `q` followed by Enter).

Hex images contain whitespace-separated hexadecimal words, with optional
`0x` prefixes and `#`, `;`, or `//` line comments. For example:

```text
1241  # ADDI r1, 1 (canonical encoding uses rs = rd)
F000  # HALT
```

Binary images are packed byte sequences; odd lengths are valid. HEX words
load as pairs of little-endian bytes at an even load address. Load/entry
addresses are byte addresses, and entry must be even. Images must fit below
byte address 10000h without wrapping. Instructions and aligned words use
two bytes. LDB/STB can access either byte lane and preserve adjacent data.
The runner loads machine code; it does not assemble mnemonic source.

## Library

```rust
use nosuz16::{Cpu, Memory, StepOutcome, HALT};

let mut memory = Memory::default();
memory.load(0, &[0x1241, HALT]).unwrap();
let mut cpu = Cpu::default();
while cpu.step(&mut memory).unwrap() != StepOutcome::Halted {}
assert_eq!(cpu.registers()[1], 1);
```

`Cpu::step` accepts any implementation of the `Bus` trait, so a different
machine can supply its own RAM and devices. Register writes use
`set_register`; r0 always reads zero and discards writes. PC and flags can
be inspected or configured directly. `Memory::load` loads aligned word arrays at byte addresses; `load_bytes`
loads packed bytes at any address. `peek`/`peek_byte` inspect backing storage
without consuming UART input. Custom buses implement word and byte reads
and writes separately to preserve device transaction semantics.

`cpu.reset()` clears CPU state and sets PC/sp to zero without changing the
memory bus. `memory.reset_devices()` clears UART queues and VIDEO data while
preserving RAM. These reset operations are independent.

Illegal instructions and alignment faults latch an error, available through `cpu.fault()`.
Further steps return that error without fetching. An explicit debugger
operation, `cpu.resume()`, clears the fault or HALT while preserving PC,
registers, and flags. Repair the instruction or adjust PC before resuming.
Guest startup code remains responsible for setting sp to FF00 before calls.

## v2.5 execution rules

The CPU and default memory bus follow the v2.5 ISA and N16-REF-2 profile.
The command-line entry address and instruction limit are runner settings.

| Area | Emulator behavior |
| --- | --- |
| Reset | A new CPU has zero PC/registers/flags and is running. A new memory bus starts at zero. CPU reset leaves the bus untouched. The CLI sets PC to the entry/load address; startup code initializes sp to FF00. |
| Arithmetic/addresses | Results, PC increments, and effective addresses wrap modulo 65536. Signed interpretation is two's complement. |
| Immediate fields | All imm6 and branch offset6 values sign-extend, range -32..31. JAL offset9 sign-extends, range -256..255. LD/ST/LDB/STB/JALR offsets use bytes; relative branch/JAL offsets use two-byte units. |
| Relative control flow | Branch and JAL offsets are relative to PC+2; links contain PC+2. Relative offsets are multiplied by two. |
| ADDI | Two-operand operation `rd += imm`, as the instruction table says. Encoded rs is ignored. Canonical assembler encoding: rs = rd. |
| Shifts | Exactly one bit. Encoded rs is ignored. Canonical assembler encoding: rs = r0. |
| Overlapping operands | All register sources are read before destinations are written, including `JALR rd, rd, imm`. |
| r0 destinations | Register write is discarded; ALU flag updates and bus read side effects still occur. |
| ALU and ADDI flags | Z indicates a zero 16-bit result; N is bit 15. C/V rules below. |
| ADD/ADDC/ADDI | C is unsigned carry out; V means the mathematical signed result, including carry input for ADDC, exceeds -32768..32767. |
| SUB/SUBC | C means borrow. SUBC subtracts the incoming C; V detects signed overflow including borrow input. |
| AND/OR/XOR | Update Z/N and clear C/V. |
| SLL/SRL/ASR | Update Z/N, set C to the bit shifted out, clear V. |
| Other instructions | LD, ST, LDB, STB, branches, jumps, and HALT preserve flags. |
| SYSTEM | Only F000 is HALT. Executing it advances PC by two bytes and makes subsequent steps inert. |
| Illegal encodings | Opcodes B..E, unknown ALU functions, and SYSTEM words other than F000 latch an error. PC/registers/flags/data memory are preserved; the initial fetch's device side effects cannot be undone. No further bus access occurs until reset or debugger resume. |
| UART FF00 | Reads consume one queued byte, zero-extended, or return zero when empty. Writes emit the low eight bits. Word reads and low-lane byte reads consume once. High-lane byte reads return zero without consuming. |
| UART FF02 | Read-only status: bit 0 = receive data ready, bit 1 = transmit ready (always set). Other bits zero. Writes ignored. |
| VIDEO FF10 | A 16-bit data register backed by packed bytes, available through `peek`; no display rendering. |

## Migrating from v2.4

Rebuild code and objects for v2.5. PC, SP, pointers, load addresses, and labels
now use byte addresses. Instructions advance PC by two. Stack PUSH/POP
subtract/add two, and stack arguments occupy sp+0, sp+2, etc. UART STATUS
moves to FF02. Word loads/stores and JALR targets must be even; an odd PC
faults before fetching. Faults preserve architectural state and latch until
reset/debugger resume.

Relative branch/JAL encodings retain instruction-sized offsets, while memory
and JALR imm6 offsets now use bytes. The new LDB/STB opcodes are 9/A. Packed
characters share a word; STB preserves the other byte. ALU flag rules and
MOV/CMP/NOP aliases remain unchanged. This runner executes images; it does
not assemble mnemonic source. The LLVM MC assembler supports v2.5.

## Validation

Tests cover all core instructions, carry/borrow chains, signed overflow,
shift flags, signed branch comparison, immediate boundaries, PC/address
wraparound, overlapping JALR operands, r0 side effects, self-modifying code,
a call/stack/return program, invalid instructions, fault latching and debugger
resume, independent CPU/device resets, UART, image loading, and
the command-line hello program and execution limit.
