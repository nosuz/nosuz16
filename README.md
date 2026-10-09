

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
