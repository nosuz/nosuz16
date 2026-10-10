use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

struct Image {
    directory: PathBuf,
    path: PathBuf,
}

impl Image {
    fn new(extension: &str, bytes: &[u8]) -> Self {
        static NEXT_ID: AtomicUsize = AtomicUsize::new(0);
        let directory = std::env::temp_dir().join(format!(
            "nosuz16-cli-{}-{}",
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&directory).unwrap();
        let path = directory.join(format!("program.{extension}"));
        fs::write(&path, bytes).unwrap();
        Self { directory, path }
    }
}

impl Drop for Image {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn command() -> Command {
    Command::new(env!("CARGO_BIN_EXE_nosuz16"))
}

fn hello_path() -> String {
    format!("{}/examples/hello.hex", env!("CARGO_MANIFEST_DIR"))
}

#[test]
fn hello_program_outputs_uart_and_halts() {
    let output = command().args(["--dump", &hello_path()]).output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, b"Hi\n");
    let state = String::from_utf8(output.stderr).unwrap();
    assert!(state.contains("PC=0028"));
    assert!(state.contains("halted=true"));
}

#[test]
fn relocated_program_runs_from_load_address() {
    let output = command()
        .args(["--load-address", "0x100", &hello_path()])
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"Hi\n");
}

#[test]
fn step_limit_reports_failure() {
    let output = command()
        .args(["--max-steps", "1", &hello_path()])
        .output()
        .unwrap();
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("instruction limit (1) reached"));
}

#[test]
fn execution_without_step_limit_can_exceed_one_million_instructions() {
    // Eight passes of a 65535-count inner loop: 1,048,586 instructions.
    let image = Image::new("hex", b"1208 143F 14BF 543E 127F 523B F000");
    let output = command()
        .arg("--dump")
        .arg(&image.path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let state = String::from_utf8_lossy(&output.stderr);
    assert!(state.contains("PC=000E"));
    assert!(state.contains("r1=0000") && state.contains("r2=0000"));
    assert!(state.contains("halted=true faulted=false"));

    let limited = command()
        .args(["--max-steps", "1000000"])
        .arg(&image.path)
        .output()
        .unwrap();
    assert!(!limited.status.success());
    assert!(
        String::from_utf8_lossy(&limited.stderr).contains("instruction limit (1000000) reached")
    );

    // Check both sides of the exact limit, including the HALT instruction.
    for (limit, succeeds, pc) in [
        ("1048585", false, "PC=000C"),
        ("1048586", true, "PC=000E"),
        ("1048587", true, "PC=000E"),
    ] {
        let output = command()
            .args(["--max-steps", limit, "--dump"])
            .arg(&image.path)
            .output()
            .unwrap();
        assert_eq!(output.status.success(), succeeds);
        assert!(String::from_utf8_lossy(&output.stderr).contains(pc));
    }
}

#[test]
fn explicit_step_limit_stops_an_infinite_loop_at_the_exact_count() {
    // JAL r0,-1 jumps back to itself without changing flags or registers.
    let image = Image::new("hex", b"71FF");
    for limit in ["3", "0x3"] {
        let output = command()
            .args(["--max-steps", limit, "--trace", "--dump"])
            .arg(&image.path)
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        let state = String::from_utf8_lossy(&output.stderr);
        assert_eq!(state.lines().filter(|line| line.starts_with("PC=")).count(), 4);
        assert!(state.contains("instruction limit (3) reached at PC=0000"));
        assert!(!state.contains("halted=true") && !state.contains("faulted=true"));
    }
}

#[test]
fn maximum_u64_step_limit_does_not_overflow() {
    let image = Image::new("hex", b"F000");
    let output = command()
        .args(["--max-steps", "18446744073709551615"])
        .arg(&image.path)
        .output()
        .unwrap();
    assert!(output.status.success());
}

#[test]
fn invalid_step_limits_are_rejected() {
    for (value, message) in [
        ("0", "--max-steps must be positive"),
        ("-1", "invalid number"),
        ("abc", "invalid number"),
        ("18446744073709551616", "invalid number"),
    ] {
        let output = command()
            .args(["--max-steps", value, &hello_path()])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert!(String::from_utf8_lossy(&output.stderr).contains(message));
    }
    let missing = command().arg("--max-steps").output().unwrap();
    assert!(!missing.status.success());
    assert!(String::from_utf8_lossy(&missing.stderr).contains("--max-steps requires a value"));
}

#[test]
fn halt_at_the_explicit_step_limit_succeeds() {
    let image = Image::new("hex", b"F000");
    let output = command()
        .args(["--max-steps", "1", "--dump"])
        .arg(&image.path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(String::from_utf8_lossy(&output.stderr).contains("halted=true faulted=false"));
}

#[test]
fn help_and_invalid_options() {
    let output = command().arg("--help").output().unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("Usage: nosuz16"));
    assert!(String::from_utf8_lossy(&output.stdout).contains("default: unlimited"));
    for args in [
        vec!["--entry", "65536"],
        vec!["--format", "elf"],
        vec!["--max-steps", "0"],
        vec!["--unknown"],
        vec![],
    ] {
        assert!(!command().args(args).output().unwrap().status.success());
    }
}

#[test]
fn binary_images_use_little_endian_words_and_explicit_entry() {
    // Skip illegal word at the load address; execute ADDI r1,1 and HALT.
    let image = Image::new("bin", &[0x00, 0x90, 0x41, 0x12, 0x00, 0xf0]);
    let output = command()
        .args(["--load-address", "0x100", "--entry", "0x102", "--dump"])
        .arg(&image.path)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.is_empty());
    let state = String::from_utf8_lossy(&output.stderr);
    assert!(state.contains("PC=0106"));
    assert!(state.contains("r1=0001"));
    assert!(state.contains("r6=0000")); // CPU does not initialize ABI sp.
    assert!(state.contains("faulted=false"));
}

#[test]
fn invalid_and_empty_images_and_faults_stop_the_runner() {
    for (extension, bytes, args, message) in [
        ("hex", &b"# empty"[..], vec![], "program image is empty"),
        ("bin", &[0x00][..], vec!["--entry", "1"], "entry byte address must be even"),
        (
            "hex",
            &b"F000 F000"[..],
            vec!["--load-address", "0xfffe"],
            "exceeds the 64-KiB",
        ),
        (
            "hex",
            &b"B000 1241 F000"[..],
            vec!["--dump"],
            "illegal instruction B000 at byte address 0000",
        ),
    ] {
        let image = Image::new(extension, bytes);
        let output = command().args(args).arg(&image.path).output().unwrap();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        let error = String::from_utf8_lossy(&output.stderr);
        assert!(error.contains(message), "{error}");
        if bytes.starts_with(b"B000") {
            assert!(error.contains("PC=0000"));
            assert!(error.contains("r1=0000"));
            assert!(error.contains("faulted=true"));
        }
    }
}

#[test]
fn odd_length_bin_can_end_in_byte_data() {
    let image=Image::new("bin",&[0,0xf0,42]);
    let output=command().args(["--dump"]).arg(&image.path).output().unwrap();
    assert!(output.status.success(),"{}",String::from_utf8_lossy(&output.stderr));
    assert!(String::from_utf8_lossy(&output.stderr).contains("PC=0002"));
}
