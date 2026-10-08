# Nosuz16 Rust emulator

A dependency-free Rust library and command-line emulator for
[Nosuz16 CPU specification v2.4](../Nosuz16_CPU_Spec.md). Implements all
18 core instructions, 64K words of unified memory, the zero register, flags,
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
instructions, invalid images, and instruction-limit exhaustion return a
nonzero status. The default instruction limit is 1,000,000, including HALT.

Hex images contain whitespace-separated hexadecimal words, with optional
`0x` prefixes and `#`, `;`, or `//` line comments. For example:

```text
1241  # ADDI r1, 1 (canonical encoding uses rs = rd)
F000  # HALT
```

Binary images serialize each word as two little-endian bytes. This is a
host file format convention; the CPU itself has no byte addressing.
Images must fit between the load address and FFFF and do not wrap.
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
be inspected or configured directly. `Memory::load` initializes backing
storage without I/O side effects; `peek` inspects that storage without
consuming UART input.

`cpu.reset()` clears CPU state and sets PC/sp to zero without changing the
memory bus. `memory.reset_devices()` clears UART queues and VIDEO data while
preserving RAM. These reset operations are independent.

Illegal instructions latch an error, available through `cpu.fault()`.
Further steps return that error without fetching. An explicit debugger
operation, `cpu.resume()`, clears the fault or HALT while preserving PC,
registers, and flags. Repair the instruction or adjust PC before resuming.
Guest startup code remains responsible for setting sp to FF00 before calls.

## v2.4 execution rules

The CPU and default memory bus follow the v2.4 ISA and N16-REF-1 profile.
The command-line entry address and instruction limit are runner settings.

| Area | Emulator behavior |
| --- | --- |
| Reset | A new CPU has zero PC/registers/flags and is running. A new memory bus starts at zero. CPU reset leaves the bus untouched. The CLI sets PC to the entry/load address; startup code initializes sp to FF00. |
| Arithmetic/addresses | Results, PC increments, and effective addresses wrap modulo 65536. Signed interpretation is two's complement. |
| Immediate fields | All imm6 and branch offset6 values sign-extend, range -32..31. JAL offset9 sign-extends, range -256..255. Offsets are in words. |
| Relative control flow | Branch and JAL offsets are relative to the incremented PC; links contain the incremented PC. |
| ADDI | Two-operand operation `rd += imm`, as the instruction table says. Encoded rs is ignored. Canonical assembler encoding: rs = rd. |
| Shifts | Exactly one bit. Encoded rs is ignored. Canonical assembler encoding: rs = r0. |
| Overlapping operands | All register sources are read before destinations are written, including `JALR rd, rd, imm`. |
| r0 destinations | Register write is discarded; ALU flag updates and bus read side effects still occur. |
| ALU and ADDI flags | Z indicates a zero 16-bit result; N is bit 15. C/V rules below. |
| ADD/ADDC/ADDI | C is unsigned carry out; V means the mathematical signed result, including carry input for ADDC, exceeds -32768..32767. |
| SUB/SUBC | C means borrow. SUBC subtracts the incoming C; V detects signed overflow including borrow input. |
| AND/OR/XOR | Update Z/N and clear C/V. |
| SLL/SRL/ASR | Update Z/N, set C to the bit shifted out, clear V. |
| Other instructions | LD, ST, branches, jumps, and HALT preserve flags. |
| SYSTEM | Only F000 is HALT. Executing it increments PC once and makes subsequent steps inert. |
| Illegal encodings | Opcodes 9..E, unknown ALU functions, and SYSTEM words other than F000 latch an error. PC/registers/flags/data memory are preserved; the initial fetch's device side effects cannot be undone. No further bus access occurs until reset or debugger resume. |
| UART FF00 | Reads consume one queued byte, zero-extended, or return zero when empty. Writes emit the low eight bits. Accesses remain 16-bit bus transactions. |
| UART FF01 | Read-only status: bit 0 = receive data ready, bit 1 = transmit ready (always set). Other bits zero. Writes ignored. |
| VIDEO FF10 | A 16-bit data register backed by word storage, available through `peek`; no display rendering. |

## Migrating assembly from v2.3

The 18 core instruction encodings are unchanged. Corrected aliases are:

| Alias | v2.4 expansion |
| --- | --- |
| MOV rd, rs | Distinct registers: `XOR rd, rd; ADD rd, rs`. Same register: `ADDI rd, 0`. Updates Z/N and clears C/V. |
| CMP rs1, rs2, tmp | `MOV tmp, rs1; SUB tmp, rs2`. Scratch tmp must differ from r0 and both inputs. The old two-operand alias is invalid. |
| NOP | `JAL r0, 0` (7000), preserving all flags. |
| SUBI rd, imm | `ADDI rd, -imm`, accepting imm in -31..32 only. |

The old NOP encoding 0000 remains legal `ADD r0, r0`, which changes flags.
MOV/CMP can expand to multiple words, so an assembler must resolve labels
and check relative ranges after expansion. This runner accepts expanded
machine code and does not implement an assembler.

The specification now defines flag formulas, immediate ranges, operand
snapshots, reset/fault behavior, register/stack ABI, and the reference
UART/VIDEO/HALT/image profile. See the spec's v2.3 change list for details.

## Validation

Tests cover all core instructions, carry/borrow chains, signed overflow,
shift flags, signed branch comparison, immediate boundaries, PC/address
wraparound, overlapping JALR operands, r0 side effects, self-modifying code,
a call/stack/return program, invalid instructions, fault latching and debugger
resume, independent CPU/device resets, UART, image loading, and
the command-line hello program and execution limit.
