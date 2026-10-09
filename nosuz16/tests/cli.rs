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
fn help_and_invalid_options() {
    let output = command().arg("--help").output().unwrap();
    assert!(output.status.success());
    assert!(String::from_utf8_lossy(&output.stdout).contains("Usage: nosuz16"));
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
