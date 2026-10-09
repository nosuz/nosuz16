use nosuz16::{
    Bus, Cpu, Flags, HALT, LoadError, Memory, StepOutcome, UART_DATA, UART_STATUS, VIDEO,
    parse_binary, parse_hex,
};

fn alu(rd: u16, rs: u16, func: u16) -> u16 {
    (rd << 9) | (rs << 6) | func
}

fn immediate(op: u16, rd: u16, rs: u16, imm: i16) -> u16 {
    (op << 12) | (rd << 9) | (rs << 6) | ((imm as u16) & 0x3f)
}

fn jump(rd: u16, offset: i16) -> u16 {
    0x7000 | (rd << 9) | ((offset as u16) & 0x1ff)
}

fn execute(cpu: &mut Cpu, word: u16) {
    let mut memory = Memory::default();
    memory.load(cpu.pc, &[word]).unwrap();
    assert_eq!(cpu.step(&mut memory), Ok(StepOutcome::Executed));
}

#[test]
fn reset_and_zero_register() {
    let mut cpu = Cpu::default();
    assert_eq!(cpu.registers(), &[0; 8]);
    assert_eq!(cpu.flags, Flags::default());
    assert_eq!(cpu.pc, 0);
    assert!(!cpu.is_halted());
    cpu.set_register(0, 0xffff);
    execute(&mut cpu, immediate(1, 0, 0, -1));
    assert_eq!(cpu.registers()[0], 0);
    assert!(cpu.flags.n);
    cpu.set_register(1, 42);
    execute(&mut cpu, alu(0, 1, 0));
    assert_eq!(cpu.registers()[0], 0);
    assert!(!cpu.flags.z);
}

#[test]
fn v25_mov_expansions_copy_and_handle_overlapping_registers() {
    // MOV r1, r2: the previous destination must not be added to the source.
    let mut cpu = Cpu::default();
    cpu.set_register(1, 5);
    cpu.set_register(2, 7);
    execute(&mut cpu, alu(1, 1, 6));
    execute(&mut cpu, alu(1, 2, 0));
    assert_eq!(cpu.registers()[1], 7);
    assert_eq!(cpu.registers()[2], 7);
    assert_eq!(cpu.flags, Flags::default());

    // MOV r1, r1: the source must survive; flag effects match other copies.
    cpu.set_register(1, 0x8000);
    cpu.flags.c = true;
    cpu.flags.v = true;
    execute(&mut cpu, immediate(1, 1, 1, 0));
    assert_eq!(cpu.registers()[1], 0x8000);
    assert_eq!(
        cpu.flags,
        Flags {
            n: true,
            ..Flags::default()
        }
    );

    // MOV r0, r2 discards the write but still evaluates source flags.
    cpu.set_register(2, 0x8000);
    execute(&mut cpu, alu(0, 0, 6));
    execute(&mut cpu, alu(0, 2, 0));
    assert_eq!(cpu.registers()[0], 0);
    assert_eq!(
        cpu.flags,
        Flags {
            n: true,
            ..Flags::default()
        }
    );

    // MOV r1, r0 copies zero.
    execute(&mut cpu, alu(1, 1, 6));
    execute(&mut cpu, alu(1, 0, 0));
    assert_eq!(cpu.registers()[1], 0);
    assert_eq!(
        cpu.flags,
        Flags {
            z: true,
            ..Flags::default()
        }
    );
}

#[test]
fn v25_cmp_expansion_compares_both_inputs_and_preserves_them() {
    for (a, b, result, expected_flags) in [
        (
            7,
            7,
            0,
            Flags {
                z: true,
                ..Flags::default()
            },
        ),
        (
            5,
            7,
            0xfffe,
            Flags {
                c: true,
                n: true,
                ..Flags::default()
            },
        ),
        (
            0x8000,
            1,
            0x7fff,
            Flags {
                v: true,
                ..Flags::default()
            },
        ),
    ] {
        let mut cpu = Cpu::default();
        cpu.set_register(1, a);
        cpu.set_register(2, b);
        cpu.set_register(3, 123);
        // CMP r1, r2, r3: MOV r3, r1; SUB r3, r2.
        execute(&mut cpu, alu(3, 3, 6));
        execute(&mut cpu, alu(3, 1, 0));
        execute(&mut cpu, alu(3, 2, 1));
        assert_eq!(cpu.registers()[1], a);
        assert_eq!(cpu.registers()[2], b);
        assert_eq!(cpu.registers()[3], result);
        assert_eq!(cpu.flags, expected_flags);
    }
}

#[test]
fn v25_nop_preserves_carry_chain_and_all_registers() {
    let mut cpu = Cpu::default();
    cpu.set_register(1, 0xffff);
    cpu.set_register(2, 1);
    cpu.set_register(3, 1);
    execute(&mut cpu, alu(1, 3, 0));
    let before = cpu.clone();
    execute(&mut cpu, 0x7000); // NOP = JAL r0, 0
    assert_eq!(cpu.registers(), before.registers());
    assert_eq!(cpu.flags, before.flags);
    assert_eq!(cpu.pc, before.pc.wrapping_add(2));
    execute(&mut cpu, alu(2, 0, 2));
    assert_eq!((cpu.registers()[2], cpu.registers()[1]), (2, 0));
}

#[test]
fn arithmetic_and_flags() {
    let cases = [
        // function, a, b, C in, result, Z, C, N, V
        (0, 0xffff, 1, false, 0, true, true, false, false),
        (0, 0x7fff, 1, false, 0x8000, false, false, true, true),
        (0, 0x8000, 0x8000, false, 0, true, true, false, true),
        (1, 0, 1, false, 0xffff, false, true, true, false),
        (1, 0x8000, 1, false, 0x7fff, false, false, false, true),
        (1, 0x7fff, 0xffff, false, 0x8000, false, true, true, true),
        (1, 42, 42, false, 0, true, false, false, false),
        (2, 0xffff, 0, true, 0, true, true, false, false),
        (2, 0x7fff, 0, true, 0x8000, false, false, true, true),
        (2, 1, 2, false, 3, false, false, false, false),
        (2, 0x8000, 0xffff, true, 0x8000, false, true, true, false),
        (3, 0, 0, true, 0xffff, false, true, true, false),
        (3, 0, 0xffff, true, 0, true, true, false, false),
        (3, 0x8000, 0, true, 0x7fff, false, false, false, true),
        (3, 0x7fff, 0xffff, true, 0x7fff, false, true, false, false),
        (3, 3, 2, false, 1, false, false, false, false),
    ];
    for (func, a, b, input_c, result, z, c, n, v) in cases {
        let mut cpu = Cpu::default();
        cpu.set_register(1, a);
        cpu.set_register(2, b);
        cpu.flags.c = input_c;
        execute(&mut cpu, alu(1, 2, func));
        assert_eq!(
            cpu.registers()[1],
            result,
            "func={func} a={a:04X} b={b:04X}"
        );
        assert_eq!(
            cpu.flags,
            Flags { z, c, n, v },
            "func={func} a={a:04X} b={b:04X}"
        );
        assert_eq!(cpu.registers()[2], b);
    }
}

#[test]
fn multiword_carry_and_borrow_chains() {
    let mut cpu = Cpu::default();
    cpu.set_register(1, 0xffff); // 0001:FFFF + 0000:0001 = 0002:0000
    cpu.set_register(2, 1);
    cpu.set_register(3, 1);
    execute(&mut cpu, alu(1, 3, 0));
    execute(&mut cpu, alu(2, 0, 2));
    assert_eq!((cpu.registers()[2], cpu.registers()[1]), (2, 0));
    execute(&mut cpu, alu(1, 3, 1));
    execute(&mut cpu, alu(2, 0, 3));
    assert_eq!((cpu.registers()[2], cpu.registers()[1]), (1, 0xffff));
}

#[test]
fn addi_signed_limits_and_unused_rs() {
    let mut cpu = Cpu::default();
    cpu.set_register(1, 1);
    cpu.set_register(2, 500);
    execute(&mut cpu, immediate(1, 1, 2, -32));
    assert_eq!(cpu.registers()[1], 0xffe1);
    execute(&mut cpu, immediate(1, 1, 7, 31));
    assert_eq!(cpu.registers()[1], 0);
    assert!(cpu.flags.z && cpu.flags.c);
}

#[test]
fn logical_instructions_clear_carry_and_overflow() {
    for (func, expected) in [(4, 0x00a0), (5, 0xfafa), (6, 0xfa5a)] {
        let mut cpu = Cpu::default();
        cpu.set_register(1, 0xf0f0);
        cpu.set_register(2, 0x0aaa);
        cpu.flags.c = true;
        cpu.flags.v = true;
        execute(&mut cpu, alu(1, 2, func));
        assert_eq!(cpu.registers()[1], expected);
        assert!(!cpu.flags.c && !cpu.flags.v);
        assert_eq!(cpu.flags.n, expected & 0x8000 != 0);
    }
    let mut cpu = Cpu::default();
    cpu.set_register(1, 42);
    execute(&mut cpu, alu(1, 1, 6));
    assert_eq!(cpu.registers()[1], 0);
    assert!(cpu.flags.z);
}

#[test]
fn shifts_are_one_bit_and_ignore_rs() {
    for (func, input, expected, carry) in [
        (7, 0x8001, 2, true),
        (7, 1, 2, false),
        (8, 0x8001, 0x4000, true),
        (8, 1, 0, true),
        (9, 0x8001, 0xc000, true),
        (9, 0x8000, 0xc000, false),
        (9, 2, 1, false),
    ] {
        let mut cpu = Cpu::default();
        cpu.set_register(1, input);
        cpu.set_register(2, 15);
        cpu.flags.v = true;
        execute(&mut cpu, alu(1, 2, func));
        assert_eq!(cpu.registers()[1], expected);
        assert_eq!(cpu.flags.c, carry);
        assert_eq!(cpu.flags.z, expected == 0);
        assert!(!cpu.flags.v);
    }
}

#[test]
fn load_store_byte_offsets_and_address_wrap() {
    let mut cpu = Cpu::default();
    let mut memory = Memory::default();
    memory
        .load(
            0,
            &[
                immediate(3, 1, 2, -2),
                immediate(2, 3, 2, -2),
                immediate(3, 1, 4, 30),
                immediate(2, 5, 4, 30),
            ],
        )
        .unwrap();
    cpu.set_register(1, 0xabcd);
    cpu.set_register(4, 0xfff0);
    cpu.flags = Flags {
        z: true,
        c: true,
        n: true,
        v: true,
    };
    for _ in 0..4 {
        cpu.step(&mut memory).unwrap();
    }
    assert_eq!(memory.peek(0xfffe), 0xabcd);
    assert_eq!(memory.peek(0x000e), 0xabcd);
    assert_eq!(cpu.registers()[3], 0xabcd);
    assert_eq!(cpu.registers()[5], 0xabcd);
    assert_eq!(
        cpu.flags,
        Flags {
            z: true,
            c: true,
            n: true,
            v: true
        }
    );
}

#[test]
fn unified_memory_supports_self_modifying_code() {
    let mut cpu = Cpu::default();
    let mut memory = Memory::default();
    memory.load(0, &[immediate(3, 1, 0, 2), 0]).unwrap();
    cpu.set_register(1, HALT);
    cpu.step(&mut memory).unwrap();
    assert_eq!(cpu.step(&mut memory), Ok(StepOutcome::Halted));
    assert_eq!(cpu.pc, 4);
}

#[test]
fn all_branch_conditions_use_registers_and_preserve_flags() {
    for (op, a, b, taken) in [
        (4, 5, 5, true),
        (4, 5, 6, false),
        (5, 5, 6, true),
        (5, 5, 5, false),
        (6, 0xffff, 1, true),
        (6, 1, 0xffff, false),
        (6, 0x8000, 0x7fff, true),
        (6, 5, 5, false),
    ] {
        let mut cpu = Cpu::default();
        cpu.pc = 100;
        cpu.set_register(1, a);
        cpu.set_register(2, b);
        cpu.flags = Flags {
            z: true,
            c: true,
            n: true,
            v: true,
        };
        execute(&mut cpu, immediate(op, 1, 2, -32));
        assert_eq!(cpu.pc, if taken { 38 } else { 102 });
        assert_eq!(
            cpu.flags,
            Flags {
                z: true,
                c: true,
                n: true,
                v: true
            }
        );
    }
    let mut cpu = Cpu::default();
    execute(&mut cpu, immediate(4, 0, 0, 31));
    assert_eq!(cpu.pc, 64);
}

#[test]
fn jal_signed_limits_links_and_wraparound() {
    let mut cpu = Cpu::default();
    cpu.pc = 100;
    execute(&mut cpu, jump(3, -256));
    assert_eq!(cpu.registers()[3], 102);
    assert_eq!(cpu.pc, 102u16.wrapping_sub(512));
    cpu.pc = 0xfffe;
    execute(&mut cpu, jump(7, 255));
    assert_eq!(cpu.registers()[7], 0);
    assert_eq!(cpu.pc, 510);
    execute(&mut cpu, jump(0, -1));
    assert_eq!(cpu.pc, 510);
    assert_eq!(cpu.registers()[0], 0);
}

#[test]
fn jalr_reads_source_before_link_write_and_ret_discards_link() {
    let mut cpu = Cpu::default();
    cpu.set_register(7, 100);
    execute(&mut cpu, immediate(8, 7, 7, -32));
    assert_eq!(cpu.pc, 68);
    assert_eq!(cpu.registers()[7], 2);
    execute(&mut cpu, immediate(8, 0, 7, 0));
    assert_eq!(cpu.pc, 2);
    assert_eq!(cpu.registers()[0], 0);
    cpu.set_register(1, 0xffff);
    execute(&mut cpu, immediate(8, 2, 1, 31));
    assert_eq!(cpu.pc, 30);
    assert_eq!(cpu.registers()[2], 4);
}

#[test]
fn call_stack_and_return_program() {
    let mut memory = Memory::default();
    memory
        .load(
            0,
            &[
                jump(7, 1), // call byte address 4, link byte address 2
                HALT,
                immediate(1, 6, 6, -2),
                immediate(3, 7, 6, 0),
                immediate(1, 1, 1, 31),
                immediate(2, 7, 6, 0),
                immediate(1, 6, 6, 2),
                immediate(8, 0, 7, 0),
            ],
        )
        .unwrap();
    let mut cpu = Cpu::default();
    cpu.set_register(6, 0x8000);
    for _ in 0..9 {
        cpu.step(&mut memory).unwrap();
    }
    assert!(cpu.is_halted());
    assert_eq!(cpu.registers()[1], 31);
    assert_eq!(cpu.registers()[6], 0x8000);
    assert_eq!(memory.peek(0x7ffe), 2);
}

#[test]
fn illegal_instructions_preserve_architectural_state_and_latch_fault() {
    for word in [
        0x000a, 0x003f, 0xb000, 0xc000, 0xd000, 0xe000, 0xf001, 0xffff,
    ] {
        let mut cpu = Cpu::default();
        cpu.pc = 124;
        cpu.set_register(1, 42);
        let before = cpu.clone();
        let mut memory = Memory::default();
        memory.load(124, &[word]).unwrap();
        let error = cpu.step(&mut memory).unwrap_err();
        assert_eq!(error.pc, 124);
        assert_eq!(error.instruction, Some(word));
        assert_eq!(cpu.pc, before.pc);
        assert_eq!(cpu.registers(), before.registers());
        assert_eq!(cpu.flags, before.flags);
        assert_eq!(cpu.is_halted(), before.is_halted());
        assert_eq!(cpu.fault(), Some(error));
        let faulted = cpu.clone();
        assert_eq!(cpu.step(&mut memory), Err(error));
        assert_eq!(cpu, faulted);
    }
}

#[test]
fn halt_is_sticky_and_fetch_wraps() {
    let mut cpu = Cpu::default();
    cpu.pc = 0xfffe;
    let mut memory = Memory::default();
    memory.load(0xfffe, &[0]).unwrap();
    memory.load(0, &[HALT]).unwrap();
    cpu.step(&mut memory).unwrap();
    assert_eq!(cpu.pc, 0);
    assert_eq!(cpu.step(&mut memory), Ok(StepOutcome::Halted));
    let before = cpu.clone();
    assert_eq!(cpu.step(&mut memory), Ok(StepOutcome::Halted));
    assert_eq!(cpu, before);
}

#[test]
fn cpu_reset_clears_halt_and_fault_without_resetting_memory_or_devices() {
    for instruction in [HALT, 0xb000] {
        let mut memory = Memory::default();
        memory.load(0, &[instruction]).unwrap();
        memory.write(0x1234, 0xbeef);
        memory.write(VIDEO, 0x9876);
        memory.queue_uart_input([0, b'X']);
        memory.write(UART_DATA, u16::from(b'Y'));
        let mut cpu = Cpu::default();
        cpu.set_register(1, 42);
        cpu.set_register(6, 0xff00);
        cpu.flags = Flags {
            z: true,
            c: true,
            n: true,
            v: true,
        };
        let _ = cpu.step(&mut memory);
        assert!(cpu.is_halted() || cpu.fault().is_some());

        cpu.reset();
        assert_eq!(cpu, Cpu::default());
        assert_eq!(memory.peek(0), instruction);
        assert_eq!(memory.read(0x1234), 0xbeef);
        assert_eq!(memory.read(VIDEO), 0x9876);
        assert_eq!(memory.read(UART_STATUS), 3);
        assert_eq!(memory.read(UART_DATA), 0); // NUL is still a queued byte.
        assert_eq!(memory.read(UART_STATUS), 3);
        assert_eq!(memory.read(UART_DATA), u16::from(b'X'));
        assert_eq!(memory.take_uart_output(), b"Y");
    }
}

#[test]
fn device_reset_clears_uart_and_video_but_preserves_ram_and_cpu() {
    let mut memory = Memory::default();
    memory.load(0, &[HALT]).unwrap();
    memory.write(0x1234, 0xbeef);
    memory.write(VIDEO, 0x9876);
    memory.queue_uart_input([b'X']);
    memory.write(UART_DATA, u16::from(b'Y'));
    let mut cpu = Cpu::default();
    cpu.set_register(1, 42);
    cpu.step(&mut memory).unwrap();
    let before = cpu.clone();

    memory.reset_devices();
    assert_eq!(memory.read(UART_STATUS), 2);
    assert_eq!(memory.read(UART_DATA), 0);
    assert!(memory.take_uart_output().is_empty());
    assert_eq!(memory.read(VIDEO), 0);
    assert_eq!(memory.read(0x1234), 0xbeef);
    assert_eq!(memory.peek(0), HALT);
    assert_eq!(cpu, before);
}

#[test]
fn fault_does_not_repeat_a_device_fetch_and_requires_debugger_resume() {
    let mut memory = Memory::default();
    memory.queue_uart_input([0x3f, b'X']); // 003F is an illegal ALU function.
    let mut cpu = Cpu::new(UART_DATA);
    let error = cpu.step(&mut memory).unwrap_err();
    assert_eq!(error.pc, UART_DATA);
    assert_eq!(error.instruction, Some(0x003f));
    assert_eq!(cpu.pc, UART_DATA);
    for _ in 0..3 {
        assert_eq!(cpu.step(&mut memory), Err(error));
    }
    assert_eq!(memory.read(UART_STATUS), 3);

    // Merely editing PC does not automatically clear the latched fault.
    cpu.pc = 0;
    memory.load(0, &[HALT]).unwrap();
    assert_eq!(cpu.step(&mut memory), Err(error));
    cpu.resume();
    assert_eq!(cpu.fault(), None);
    assert_eq!(cpu.step(&mut memory), Ok(StepOutcome::Halted));
    assert_eq!(memory.read(UART_DATA), u16::from(b'X'));
}

#[test]
fn halted_cpu_never_accesses_bus_until_debugger_resume() {
    struct CountingBus {
        reads: usize,
        writes: usize,
        word: u16,
    }
    impl Bus for CountingBus {
        fn read(&mut self, _: u16) -> u16 {
            self.reads += 1;
            self.word
        }
        fn write(&mut self, _: u16, _: u16) { self.writes += 1; }
        fn read_byte(&mut self, address: u16) -> u8 { self.read(address) as u8 }
        fn write_byte(&mut self, address: u16, value: u8) { self.write(address, value as u16); }
    }
    let mut bus = CountingBus {
        reads: 0,
        writes: 0,
        word: HALT,
    };
    let mut cpu = Cpu::default();
    cpu.set_register(1, 42);
    cpu.flags.c = true;
    assert_eq!(cpu.step(&mut bus), Ok(StepOutcome::Halted));
    let before = cpu.clone();
    for _ in 0..3 {
        assert_eq!(cpu.step(&mut bus), Ok(StepOutcome::Halted));
    }
    assert_eq!((bus.reads, bus.writes), (1, 0));
    assert_eq!(cpu, before);

    cpu.resume();
    assert!(!cpu.is_halted());
    assert_eq!(cpu.pc, before.pc);
    assert_eq!(cpu.registers(), before.registers());
    assert_eq!(cpu.flags, before.flags);
    bus.word = 0x7000; // flag-preserving NOP
    assert_eq!(cpu.step(&mut bus), Ok(StepOutcome::Executed));
    assert_eq!((bus.reads, bus.writes), (2, 0));
    assert_eq!(cpu.pc, 4);
    assert_eq!(cpu.flags, before.flags);
}

#[test]
fn overlapping_load_store_operands_and_store_zero_follow_v25() {
    let mut memory = Memory::default();
    memory
        .load(
            0,
            &[
                immediate(2, 1, 1, 2),
                immediate(3, 2, 2, -32),
                immediate(3, 0, 2, -32),
            ],
        )
        .unwrap();
    memory.write(0x0102, 0xabcd);
    let mut cpu = Cpu::default();
    cpu.set_register(1, 0x0100);
    cpu.set_register(2, 0x0100);
    cpu.step(&mut memory).unwrap();
    assert_eq!(cpu.registers()[1], 0xabcd);
    cpu.step(&mut memory).unwrap();
    assert_eq!(memory.read(0x00e0), 0x0100);
    cpu.step(&mut memory).unwrap();
    assert_eq!(memory.read(0x00e0), 0);
}

#[test]
fn uart_status_input_output_and_video_storage() {
    let mut memory = Memory::default();
    assert_eq!(memory.read(UART_STATUS), 2);
    assert_eq!(memory.read(UART_DATA), 0);
    memory.queue_uart_input([b'A', b'B']);
    assert_eq!(memory.read(UART_STATUS), 3);
    assert_eq!(memory.read(UART_DATA), 65);
    assert_eq!(memory.read(UART_DATA), 66);
    assert_eq!(memory.read(UART_STATUS), 2);
    memory.write(UART_DATA, 0x1243);
    assert_eq!(memory.take_uart_output(), b"C");
    assert!(memory.take_uart_output().is_empty());
    memory.write(UART_STATUS, 0xffff);
    assert_eq!(memory.read(UART_STATUS), 2);
    memory.write(VIDEO, 0xabcd);
    assert_eq!(memory.read(VIDEO), 0xabcd);
}

#[test]
fn load_into_r0_still_consumes_uart_input() {
    let mut cpu = Cpu::default();
    cpu.set_register(1, UART_DATA);
    let mut memory = Memory::default();
    memory.load(0, &[immediate(2, 0, 1, 0)]).unwrap();
    memory.queue_uart_input([b'X']);
    cpu.step(&mut memory).unwrap();
    assert_eq!(cpu.registers()[0], 0);
    assert_eq!(memory.read(UART_STATUS), 2);
}

#[test]
fn loaders_validate_formats_and_boundaries_without_partial_loads() {
    assert_eq!(
        parse_hex("0000 0x1234 ; ignored\nF000 // stop\n# end"),
        Ok(vec![0, 0x1234, HALT])
    );
    assert_eq!(parse_binary(&[0x34, 0x12, 0, 0xf0]), Ok(vec![0x34, 0x12, 0, 0xf0]));
    assert_eq!(parse_binary(&[1]), Ok(vec![1]));
    for token in ["10000", "-1", "0x", "+1", "123g"] {
        assert!(matches!(
            parse_hex(token),
            Err(LoadError::InvalidHex { line: 1, .. })
        ));
    }
    assert_eq!(parse_binary(&vec![0; 65537]), Err(LoadError::TooLarge));
    let mut memory = Memory::default();
    memory.load(0xfffe, &[123]).unwrap();
    assert_eq!(memory.load(0xfffe, &[1, 2]), Err(LoadError::TooLarge));
    assert_eq!(memory.peek(0xfffe), 123);
    memory.load(UART_DATA, &[0x1234]).unwrap();
    assert!(memory.take_uart_output().is_empty());
    assert_eq!(memory.peek(UART_DATA), 0x1234);
}

#[test]
fn packed_bytes_preserve_neighbors_and_zero_extend_loads() {
    let mut memory = Memory::default();
    memory.write(0x1000, 0x1234);
    assert_eq!(memory.peek_byte(0x1000), 0x34);
    assert_eq!(memory.peek_byte(0x1001), 0x12);
    memory.load(0, &[immediate(10, 1, 2, 1), immediate(9, 3, 2, 1)]).unwrap();
    let mut cpu = Cpu::default();
    cpu.set_register(1, 0xffab);
    cpu.set_register(2, 0x1000);
    cpu.flags.c = true;
    cpu.step(&mut memory).unwrap();
    cpu.step(&mut memory).unwrap();
    assert_eq!(memory.peek(0x1000), 0xab34);
    assert_eq!(cpu.registers()[3], 0x00ab);
    assert!(cpu.flags.c);
    assert_eq!(cpu.pc, 4);
    memory.load_bytes(0xffff, &[0x80]).unwrap();
    cpu.set_register(2, 0xffff);
    memory.load(cpu.pc,&[immediate(9,1,2,0)]).unwrap();
    cpu.step(&mut memory).unwrap();
    assert_eq!(cpu.registers()[1], 0x80);
}

#[test]
fn alignment_faults_are_precise_and_do_not_access_data_bus() {
    struct RecordingBus { memory: Memory, reads: usize, writes: usize }
    impl Bus for RecordingBus {
        fn read(&mut self, a: u16) -> u16 { self.reads += 1; self.memory.read(a) }
        fn write(&mut self, a: u16, v: u16) { self.writes += 1; self.memory.write(a,v); }
        fn read_byte(&mut self, a: u16) -> u8 { self.reads += 1; self.memory.read_byte(a) }
        fn write_byte(&mut self, a: u16, v: u8) { self.writes += 1; self.memory.write_byte(a,v); }
    }
    for opcode in [2,3,8] {
        let mut bus = RecordingBus { memory: Memory::default(), reads: 0, writes: 0 };
        let instruction = immediate(opcode,1,2,1);
        bus.memory.load(0,&[instruction]).unwrap();
        let mut cpu = Cpu::default();
        cpu.set_register(1,0x1234);cpu.set_register(2,0x1000);cpu.flags.c=true;
        let before = cpu.clone();
        let error = cpu.step(&mut bus).unwrap_err();
        assert_eq!(error.instruction,Some(instruction));
        assert_eq!(cpu.pc,before.pc);assert_eq!(cpu.registers(),before.registers());
        assert_eq!(cpu.flags,before.flags);
        assert_eq!((bus.reads,bus.writes),(1,0));
        assert_eq!(cpu.step(&mut bus),Err(error));
        assert_eq!((bus.reads,bus.writes),(1,0));
        assert!(matches!(error.kind,nosuz16::FaultKind::Alignment { address: 0x1001, .. }));
    }
    let mut bus = RecordingBus { memory: Memory::default(), reads: 0, writes: 0 };
    let mut cpu = Cpu::new(1);
    let error = cpu.step(&mut bus).unwrap_err();
    assert_eq!(error.instruction,None);
    assert_eq!((bus.reads,bus.writes),(0,0));
}

#[test]
fn uart_byte_lanes_and_video_byte_writes_follow_ref2() {
    let mut memory = Memory::default();
    memory.queue_uart_input([0,b'A']);
    assert_eq!(memory.read_byte(UART_DATA+1),0);
    assert_eq!(memory.read_byte(UART_STATUS),3);
    assert_eq!(memory.read_byte(UART_STATUS+1),0);
    assert_eq!(memory.read(UART_DATA),0);
    assert_eq!(memory.read_byte(UART_STATUS),3);
    assert_eq!(memory.read_byte(UART_DATA),b'A');
    assert_eq!(memory.read(UART_STATUS),2);
    memory.write_byte(UART_DATA+1,b'X');
    memory.write_byte(UART_DATA,b'Y');
    assert_eq!(memory.take_uart_output(),b"Y");
    memory.write(VIDEO,0xab12);
    memory.write_byte(VIDEO+1,0xcd);
    assert_eq!(memory.read(VIDEO),0xcd12);
    assert_eq!(memory.read_byte(VIDEO),0x12);
    memory.load_bytes(VIDEO,&[0x34]).unwrap();
    assert_eq!(memory.read(VIDEO),0xcd34);
}

#[test]
fn odd_binary_data_and_last_byte_load_have_no_implicit_padding() {
    assert_eq!(parse_binary(&[0,0xf0,42]),Ok(vec![0,0xf0,42]));
    let mut memory=Memory::default();
    memory.load_bytes(0xffff,&[42]).unwrap();
    assert_eq!(memory.peek_byte(0xffff),42);
    assert_eq!(memory.load_bytes(0xffff,&[1,2]),Err(LoadError::TooLarge));
    assert_eq!(memory.peek_byte(0xffff),42);
    assert_eq!(memory.load(1,&[HALT]),Err(LoadError::UnalignedHexOrigin));
}
