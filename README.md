

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

```bash
docker build -f .devcontainer/Dockerfile -t nosuz16-dev .
docker run --rm -v "$PWD:/workspaces" nosuz16-dev nosuz16-cc llvm-nosuz16/examples/hello.c hello.bin
docker run --rm -v "$PWD:/workspaces" nosuz16-dev nosuz16 --dump hello.bin
```

See [SDK contents and usage](llvm-nosuz16/README.md#docker-sdk) for details.
