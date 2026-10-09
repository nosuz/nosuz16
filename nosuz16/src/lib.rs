//! Emulator for the Nosuz16 v2.5 byte-addressed CPU.
//!
//! See the specification for flag rules and the N16-REF-2 SYSTEM/I/O profile.

use std::collections::VecDeque;
use std::fmt;

pub const MEMORY_BYTES: usize = 65_536;
pub const MEMORY_WORDS: usize = MEMORY_BYTES / 2;
pub const UART_DATA: u16 = 0xff00;
pub const UART_STATUS: u16 = 0xff02;
pub const VIDEO: u16 = 0xff10;
pub const HALT: u16 = 0xf000;

/// A byte-addressed bus. Word transactions require even addresses.
/// Reads may have side effects, such as consuming UART input.
pub trait Bus {
    fn read(&mut self, address: u16) -> u16;
    fn write(&mut self, address: u16, value: u16);
    fn read_byte(&mut self, address: u16) -> u8;
    fn write_byte(&mut self, address: u16, value: u8);
}

/// N16-REF-2 unified RAM, UART at FF00/FF02, and VIDEO data at FF10.
pub struct Memory {
    bytes: Box<[u8]>,
    uart_input: VecDeque<u8>,
    uart_output: Vec<u8>,
}

impl Default for Memory {
    fn default() -> Self {
        Self {
            bytes: vec![0; MEMORY_BYTES].into_boxed_slice(),
            uart_input: VecDeque::new(),
            uart_output: Vec::new(),
        }
    }
}

impl Memory {
    /// Reset UART queues and VIDEO data without clearing RAM.
    /// This is independent of CPU reset.
    pub fn reset_devices(&mut self) {
        self.uart_input.clear();
        self.uart_output.clear();
        self.bytes[usize::from(VIDEO)] = 0;
        self.bytes[usize::from(VIDEO) + 1] = 0;
    }

    /// Load raw storage without triggering memory-mapped I/O.
    pub fn load(&mut self, origin: u16, words: &[u16]) -> Result<(), LoadError> {
        if origin & 1 != 0 {
            return Err(LoadError::UnalignedHexOrigin);
        }
        let bytes: Vec<_> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        self.load_bytes(origin, &bytes)
    }

    /// Load packed byte storage without device transactions, including odd sizes.
    pub fn load_bytes(&mut self, origin: u16, bytes: &[u8]) -> Result<(), LoadError> {
        let start = usize::from(origin);
        if bytes.len() > MEMORY_BYTES - start {
            return Err(LoadError::TooLarge);
        }
        self.bytes[start..start + bytes.len()].copy_from_slice(bytes);
        Ok(())
    }

    /// Inspect backing storage without I/O side effects.
    pub fn peek(&self, address: u16) -> u16 {
        u16::from_le_bytes([
            self.peek_byte(address),
            self.peek_byte(address.wrapping_add(1)),
        ])
    }

    pub fn peek_byte(&self, address: u16) -> u8 {
        self.bytes[usize::from(address)]
    }

    pub fn queue_uart_input(&mut self, bytes: impl IntoIterator<Item = u8>) {
        self.uart_input.extend(bytes);
    }

    pub fn take_uart_output(&mut self) -> Vec<u8> {
        std::mem::take(&mut self.uart_output)
    }
}

impl Bus for Memory {
    fn read(&mut self, address: u16) -> u16 {
        assert_eq!(address & 1, 0, "word bus address must be even");
        match address {
            UART_DATA => self.uart_input.pop_front().map(u16::from).unwrap_or(0),
            UART_STATUS => 2 | u16::from(!self.uart_input.is_empty()),
            _ => self.peek(address),
        }
    }

    fn write(&mut self, address: u16, value: u16) {
        assert_eq!(address & 1, 0, "word bus address must be even");
        match address {
            UART_DATA => self.uart_output.push(value as u8),
            UART_STATUS => {}
            _ => {
                let pair = value.to_le_bytes();
                self.bytes[usize::from(address)] = pair[0];
                self.bytes[usize::from(address) + 1] = pair[1];
            }
        }
    }
    fn read_byte(&mut self, address: u16) -> u8 {
        match address {
            UART_DATA => self.uart_input.pop_front().unwrap_or(0),
            0xff01 | 0xff03 => 0,
            UART_STATUS => 2 | u8::from(!self.uart_input.is_empty()),
            _ => self.peek_byte(address),
        }
    }
    fn write_byte(&mut self, address: u16, value: u8) {
        match address {
            UART_DATA => self.uart_output.push(value),
            0xff01 | UART_STATUS | 0xff03 => {}
            _ => self.bytes[usize::from(address)] = value,
        }
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct Flags {
    pub z: bool,
    /// Carry on addition, borrow on subtraction, shifted-out bit on shifts.
    pub c: bool,
    pub n: bool,
    pub v: bool,
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Cpu {
    registers: [u16; 8],
    pub pc: u16,
    pub flags: Flags,
    halted: bool,
    fault: Option<CpuError>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepOutcome {
    Executed,
    Halted,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CpuError {
    pub pc: u16,
    pub instruction: Option<u16>,
    pub kind: FaultKind,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FaultKind {
    IllegalInstruction,
    Alignment {
        access: &'static str,
        address: u16,
    },
}

impl fmt::Display for CpuError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.kind {
            FaultKind::IllegalInstruction => write!(
                f,
                "illegal instruction {:04X} at byte address {:04X}",
                self.instruction.unwrap(),
                self.pc
            ),
            FaultKind::Alignment { access, address } => write!(
                f,
                "alignment fault: {access} at byte address {address:04X}, PC={:04X}",
                self.pc
            ),
        }
    }
}

impl std::error::Error for CpuError {}

impl Cpu {
    pub fn new(entry: u16) -> Self {
        Self {
            pc: entry,
            ..Self::default()
        }
    }

    /// Restore v2.5 CPU reset state, including PC=0 and sp=0.
    /// Memory and devices are untouched; guest startup code initializes sp.
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    /// Explicit debugger operation: clear HALT/fault and retry at the current PC.
    /// Register values and flags are preserved. Repair the instruction or change
    /// PC before resuming an illegal-instruction fault.
    pub fn resume(&mut self) {
        self.halted = false;
        self.fault = None;
    }

    /// Latched illegal-instruction fault, cleared only by reset or debugger resume.
    pub fn fault(&self) -> Option<CpuError> {
        self.fault
    }

    pub fn registers(&self) -> &[u16; 8] {
        &self.registers
    }

    /// Register indices must be in 0..8. Writes to r0 are discarded.
    pub fn set_register(&mut self, index: usize, value: u16) {
        assert!(index < 8, "register index out of range");
        if index != 0 {
            self.registers[index] = value;
        }
    }

    pub fn is_halted(&self) -> bool {
        self.halted
    }

    /// Execute one instruction. An illegal instruction or alignment fault preserves PC, registers,
    /// flags, and data memory, and latches a fault. Subsequent steps return that
    /// error without accessing the bus until reset or debugger resume.
    /// The initial instruction-fetch side effects cannot be rolled back.
    pub fn step(&mut self, bus: &mut impl Bus) -> Result<StepOutcome, CpuError> {
        if let Some(error) = self.fault {
            return Err(error);
        }
        if self.halted {
            return Ok(StepOutcome::Halted);
        }
        if self.pc & 1 != 0 {
            let error = CpuError {
                pc: self.pc,
                instruction: None,
                kind: FaultKind::Alignment {
                    access: "fetch",
                    address: self.pc,
                },
            };
            self.fault = Some(error);
            return Err(error);
        }
        let instruction = bus.read(self.pc);
        let opcode = instruction >> 12;
        let rd = usize::from((instruction >> 9) & 7);
        let rs = usize::from((instruction >> 6) & 7);
        let func = instruction & 0x3f;
        if (opcode > 10 && instruction != HALT) || (opcode == 0 && func > 9) {
            let error = CpuError {
                pc: self.pc,
                instruction: Some(instruction),
                kind: FaultKind::IllegalInstruction,
            };
            self.fault = Some(error);
            return Err(error);
        }
        let imm = sign_extend(instruction & 0x3f, 6);
        let a = self.registers[rd];
        let b = self.registers[rs];
        let address = b.wrapping_add(imm);
        if matches!(opcode, 2 | 3 | 8) && address & 1 != 0 {
            let error = CpuError {
                pc: self.pc,
                instruction: Some(instruction),
                kind: FaultKind::Alignment {
                    access: match opcode {
                        2 => "load",
                        3 => "store",
                        _ => "jump",
                    },
                    address,
                },
            };
            self.fault = Some(error);
            return Err(error);
        }
        self.pc = self.pc.wrapping_add(2);
        match opcode {
            0 => {
                let result = match func {
                    0 => self.add(a, b, false),
                    1 => self.sub(a, b, false),
                    2 => self.add(a, b, self.flags.c),
                    3 => self.sub(a, b, self.flags.c),
                    4 => self.logical(a & b),
                    5 => self.logical(a | b),
                    6 => self.logical(a ^ b),
                    7 => self.shift(a.wrapping_shl(1), a & 0x8000 != 0),
                    8 => self.shift(a >> 1, a & 1 != 0),
                    9 => self.shift(((a as i16) >> 1) as u16, a & 1 != 0),
                    _ => unreachable!(),
                };
                self.set_register(rd, result);
            }
            1 => {
                let result = self.add(a, imm, false);
                self.set_register(rd, result);
            }
            2 => {
                let value = bus.read(b.wrapping_add(imm));
                self.set_register(rd, value);
            }
            3 => bus.write(b.wrapping_add(imm), a),
            4..=6 => {
                let taken = match opcode {
                    4 => a == b,
                    5 => a != b,
                    6 => (a as i16) < (b as i16),
                    _ => unreachable!(),
                };
                if taken {
                    self.pc = self.pc.wrapping_add(imm.wrapping_mul(2));
                }
            }
            7 => {
                self.set_register(rd, self.pc);
                self.pc = self.pc.wrapping_add(sign_extend(instruction & 0x1ff, 9).wrapping_mul(2));
            }
            8 => {
                // b was read before updating rd, including when rd == rs.
                self.set_register(rd, self.pc);
                self.pc = b.wrapping_add(imm);
            }
            9 => { let value = bus.read_byte(address); self.set_register(rd, u16::from(value)); }
            10 => bus.write_byte(address, a as u8),
            15 => {
                self.halted = true;
                return Ok(StepOutcome::Halted);
            }
            _ => unreachable!(),
        }
        Ok(StepOutcome::Executed)
    }

    fn add(&mut self, a: u16, b: u16, carry: bool) -> u16 {
        let wide = u32::from(a) + u32::from(b) + u32::from(carry);
        let signed = i32::from(a as i16) + i32::from(b as i16) + i32::from(carry);
        let result = wide as u16;
        self.update_flags(result, wide > 0xffff, !(-32768..=32767).contains(&signed));
        result
    }

    fn sub(&mut self, a: u16, b: u16, borrow: bool) -> u16 {
        let subtrahend = u32::from(b) + u32::from(borrow);
        let signed = i32::from(a as i16) - i32::from(b as i16) - i32::from(borrow);
        let result = a.wrapping_sub(b).wrapping_sub(u16::from(borrow));
        self.update_flags(
            result,
            u32::from(a) < subtrahend,
            !(-32768..=32767).contains(&signed),
        );
        result
    }

    fn logical(&mut self, result: u16) -> u16 {
        self.update_flags(result, false, false);
        result
    }

    fn shift(&mut self, result: u16, carry: bool) -> u16 {
        self.update_flags(result, carry, false);
        result
    }

    fn update_flags(&mut self, result: u16, c: bool, v: bool) {
        self.flags = Flags {
            z: result == 0,
            c,
            n: result & 0x8000 != 0,
            v,
        };
    }
}

fn sign_extend(value: u16, bits: u32) -> u16 {
    (((value << (16 - bits)) as i16) >> (16 - bits)) as u16
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoadError {
    TooLarge,
    UnalignedHexOrigin,
    InvalidHex { line: usize, token: String },
}

impl fmt::Display for LoadError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TooLarge => write!(f, "program exceeds the 64-KiB byte address space"),
            Self::UnalignedHexOrigin => write!(f, "HEX word load address must be even"),
            Self::InvalidHex { line, token } => {
                write!(f, "invalid hexadecimal word {token:?} on line {line}")
            }
        }
    }
}

impl std::error::Error for LoadError {}

/// Parse hexadecimal words separated by whitespace, with #, ; or // comments.
pub fn parse_hex(source: &str) -> Result<Vec<u16>, LoadError> {
    let mut words = Vec::new();
    for (index, line) in source.lines().enumerate() {
        let line = line.split("//").next().unwrap_or("");
        let line = line.split(['#', ';']).next().unwrap_or("");
        for token in line.split_whitespace() {
            let digits = token
                .strip_prefix("0x")
                .or_else(|| token.strip_prefix("0X"))
                .unwrap_or(token);
            // No sign or separators: each token must be an actual hex word.
            let word = if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_hexdigit()) {
                u16::from_str_radix(digits, 16).ok()
            } else {
                None
            };
            words.push(word.ok_or_else(|| LoadError::InvalidHex {
                line: index + 1,
                token: token.to_owned(),
            })?);
            if words.len() > MEMORY_WORDS {
                return Err(LoadError::TooLarge);
            }
        }
    }
    Ok(words)
}

/// BIN images are packed bytes; odd byte lengths are valid.
pub fn parse_binary(bytes: &[u8]) -> Result<Vec<u8>, LoadError> {
    if bytes.len() > MEMORY_BYTES {
        return Err(LoadError::TooLarge);
    }
    Ok(bytes.to_vec())
}
