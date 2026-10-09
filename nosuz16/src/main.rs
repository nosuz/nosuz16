use nosuz16::{Cpu, Memory, StepOutcome, parse_binary, parse_hex};
use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::ExitCode;

const HELP: &str = "Usage: nosuz16 [OPTIONS] PROGRAM

Run a Nosuz16 v2.5 machine-code image. UART output is written to stdout.

Options:
  --format hex|bin       Image format (default: bin for .bin, otherwise hex)
  --load-address ADDR    First byte address (default: 0)
  --entry ADDR           Initial PC (default: load address)
  --max-steps COUNT     Instruction limit (default: 1000000)
  --uart-input TEXT     Queue UTF-8 bytes for UART reads
  --trace               Print CPU state before each step to stderr
  --dump                Print final CPU state to stderr
  -h, --help            Show this help

Addresses accept decimal or 0x-prefixed hexadecimal. Hex images contain
whitespace-separated 16-bit words; #, ; and // introduce line comments.
Binary images contain packed bytes; odd byte lengths are valid. SYSTEM word F000 halts.
";

#[derive(Default)]
struct Options {
    program: Option<PathBuf>,
    format: Option<String>,
    origin: u16,
    entry: Option<u16>,
    max_steps: Option<u64>,
    input: String,
    trace: bool,
    dump: bool,
}

fn number(value: &str) -> Result<u64, String> {
    let parsed = if let Some(hex) = value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        u64::from_str_radix(hex, 16)
    } else {
        value.parse()
    };
    parsed.map_err(|_| format!("invalid number: {value}"))
}

fn address(value: &str) -> Result<u16, String> {
    u16::try_from(number(value)?).map_err(|_| format!("byte address out of range: {value}"))
}

fn options() -> Result<Option<Options>, String> {
    let mut options = Options::default();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "-h" | "--help" => return Ok(None),
            "--trace" => options.trace = true,
            "--dump" => options.dump = true,
            "--format" | "--load-address" | "--entry" | "--max-steps" | "--uart-input" => {
                let value = args
                    .next()
                    .ok_or_else(|| format!("{arg} requires a value"))?;
                match arg.as_str() {
                    "--format" => {
                        if !matches!(value.as_str(), "hex" | "bin") {
                            return Err("--format must be hex or bin".to_owned());
                        }
                        options.format = Some(value);
                    }
                    "--load-address" => options.origin = address(&value)?,
                    "--entry" => options.entry = Some(address(&value)?),
                    "--max-steps" => {
                        let limit = number(&value)?;
                        if limit == 0 {
                            return Err("--max-steps must be positive".to_owned());
                        }
                        options.max_steps = Some(limit);
                    }
                    "--uart-input" => options.input = value,
                    _ => unreachable!(),
                }
            }
            "--" => {
                for path in args.by_ref() {
                    if options.program.replace(PathBuf::from(path)).is_some() {
                        return Err("provide exactly one program image".to_owned());
                    }
                }
            }
            _ if arg.starts_with('-') => return Err(format!("unknown option: {arg}")),
            _ => {
                if options.program.replace(PathBuf::from(arg)).is_some() {
                    return Err("provide exactly one program image".to_owned());
                }
            }
        }
    }
    if options.program.is_none() {
        return Err("missing program image; use --help for usage".to_owned());
    }
    Ok(Some(options))
}

fn print_state(cpu: &Cpu) {
    let r = cpu.registers();
    let f = cpu.flags;
    eprintln!(
        "PC={:04X} r0={:04X} r1={:04X} r2={:04X} r3={:04X} r4={:04X} r5={:04X} r6={:04X} r7={:04X} Z={} C={} N={} V={} halted={} faulted={}",
        cpu.pc,
        r[0],
        r[1],
        r[2],
        r[3],
        r[4],
        r[5],
        r[6],
        r[7],
        u8::from(f.z),
        u8::from(f.c),
        u8::from(f.n),
        u8::from(f.v),
        cpu.is_halted(),
        cpu.fault().is_some()
    );
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let Some(options) = options()? else {
        print!("{HELP}");
        return Ok(());
    };
    let path = options.program.as_ref().unwrap();
    let format = options.format.as_deref().unwrap_or_else(|| {
        if path.extension().is_some_and(|extension| extension == "bin") {
            "bin"
        } else {
            "hex"
        }
    });
    let bytes = fs::read(path)?;
    let image = match format {
        "bin" => parse_binary(&bytes)?,
        _ => {
            if options.origin & 1 != 0 {
                return Err("HEX word load address must be even".into());
            }
            parse_hex(std::str::from_utf8(&bytes)?)?
                .into_iter()
                .flat_map(u16::to_le_bytes)
                .collect()
        }
    };
    if image.is_empty() {
        return Err("program image is empty".into());
    }
    let entry = options.entry.unwrap_or(options.origin);
    if entry & 1 != 0 {
        return Err("entry byte address must be even".into());
    }
    let mut memory = Memory::default();
    memory.load_bytes(options.origin, &image)?;
    memory.queue_uart_input(options.input.bytes());
    let mut cpu = Cpu::new(entry);
    let max_steps = options.max_steps.unwrap_or(1_000_000);
    let mut output = io::stdout().lock();
    let mut halted = false;
    let mut execution_error = None;
    for _ in 0..max_steps {
        if options.trace {
            print_state(&cpu);
        }
        let result = cpu.step(&mut memory);
        let bytes = memory.take_uart_output();
        if !bytes.is_empty() {
            output.write_all(&bytes)?;
            output.flush()?;
        }
        match result {
            Ok(StepOutcome::Halted) => {
                halted = true;
                break;
            }
            Ok(StepOutcome::Executed) => {}
            Err(error) => {
                execution_error = Some(error);
                break;
            }
        }
    }
    if options.dump {
        print_state(&cpu);
    }
    if let Some(error) = execution_error {
        return Err(error.into());
    }
    if !halted {
        return Err(format!(
            "instruction limit ({max_steps}) reached at PC={:04X}",
            cpu.pc
        )
        .into());
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("nosuz16: {error}");
            ExitCode::FAILURE
        }
    }
}
