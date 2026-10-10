

## LLVM backend

The experimental implementation and build/run instructions are in
[llvm-nosuz16](llvm-nosuz16/README.md).

See the [Nosuz16 LLVM backend implementation plan](LLVM_BACKEND_PLAN.md) for
the scope, implementation stages, memory-model decision, and validation criteria.

The toolchain also includes an experimental C frontend with ordinary packed byte-addressed memory access:

```bash
./llvm-nosuz16/scripts/compile-c.sh llvm-nosuz16/examples/hello.c /tmp/hello.hex
```

```bash
apt install cmake ninja-build lld zlib1g-dev libzstd-dev
git clone --depth 1 https://github.com/llvm/llvm-project.git
```

## Nosuz16 software-development container

The [.devcontainer/Dockerfile](.devcontainer/Dockerfile) builds the toolchain
in the `builder` stage, builds the emulator in `emulator-builder`, and installs
selected compiler tools, runtime, and emulator in the final `dev` stage.
Git/SSH, uv, Codex, Claude, and locale settings
remain available.
It fetches the pinned LLVM revision; a local LLVM checkout is unnecessary.

The first container build can take over an hour because it compiles LLVM and
Clang from source. Later builds can reuse Docker's cached toolchain layers.

```bash
docker build -f .devcontainer/Dockerfile -t nosuz16-dev .
docker run --rm -v "$PWD:/workspaces" nosuz16-dev nosuz16-cc llvm-nosuz16/examples/hello.c hello.bin
docker run --rm -v "$PWD:/workspaces" nosuz16-dev nosuz16 --dump hello.bin
```

See [SDK contents and usage](llvm-nosuz16/README.md#docker-sdk) for details.

## Run the demos

Run these commands inside the development container, from `/workspaces`.
`nosuz16-cc` compiles a C program and links the supplied runtime into a
machine-code image. `nosuz16` executes that image and writes UART output to
the terminal. Use the workspace sources so newly added demos are available
without rebuilding the container image.

### Hello world

Prints `Hi` followed by a newline. `--dump` also displays the final CPU state;
the program returns 42 in register `r1`.

```bash
nosuz16-cc llvm-nosuz16/examples/hello.c /tmp/hello.bin
nosuz16 --dump /tmp/hello.bin
```

### UART echo

Echoes the byte supplied through `--uart-input`, producing `A`.

```bash
nosuz16-cc llvm-nosuz16/examples/echo.c /tmp/echo.bin
nosuz16 --uart-input A /tmp/echo.bin
```

### Formatted output

Prints `Hello Nosuz16! value=-123 hex=BEEF %` followed by a newline.

```bash
nosuz16-cc llvm-nosuz16/examples/printf.c /tmp/printf.bin
nosuz16 /tmp/printf.bin
```

### Line buffer

Reads the queued input until a newline and prints `You typed: Hello`.
The Bash `$'Hello\n'` syntax supplies the terminating newline.

```bash
nosuz16-cc llvm-nosuz16/examples/read-line.c /tmp/read-line.bin
nosuz16 --uart-input $'Hello\n' /tmp/read-line.bin
```

### Mandelbrot ASCII art

Renders a 79×25 image with hexadecimal escape counts and a blank interior,
using fixed-point arithmetic. See the [sample output](llvm-nosuz16/examples/mandelbrot.txt).

```bash
nosuz16-cc llvm-nosuz16/examples/mandelbrot.c /tmp/mandelbrot.bin
nosuz16 /tmp/mandelbrot.bin
```

Execution has no step limit by default. Add `--max-steps COUNT` when you
want to bound a run, for example `nosuz16 --max-steps 500000000 /tmp/mandelbrot.bin`.

### Othello: human versus CPU

Play on an ASCII 8×8 board. X always moves first.
Choose `1` to play first as `X`, or `2` for the CPU to play first as `X`
while you play `O`, then Enter.
Enter a column and row such as `d3`, then press Enter. Enter `q` to quit.
Invalid moves are rejected, and a player with no legal move passes
automatically. The game ends when neither player can move and reports the
disc counts and winner. The CPU searches up to four moves ahead with a
bounded alpha-beta search, evaluates mobility and corner control, and
attempts deeper searches in small endgames.

```bash
nosuz16-cc llvm-nosuz16/examples/othello.c /tmp/othello.bin
nosuz16 /tmp/othello.bin
```

The emulator always connects UART to stdin/stdout. To play immediately from the
workspace without rebuilding the container:

```bash
cargo run --release --manifest-path nosuz16/Cargo.toml -- /tmp/othello.bin
```

For a scripted opening followed by quitting:

```bash
nosuz16 --uart-input $'1\nd3\nq\n' /tmp/othello.bin
```

### LLVM IR example

Compile the handwritten IR version of Hello world with `nosuz16-ir`:

```bash
nosuz16-ir llvm-nosuz16/examples/hello.ll /tmp/hello-ir.hex
nosuz16 /tmp/hello-ir.hex
```

For native builds outside Docker, follow the
[toolchain build instructions](llvm-nosuz16/README.md#build-and-run) and use
`llvm-nosuz16/scripts/compile-c.sh` or `compile.sh` to compile the demos.
