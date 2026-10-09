#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
llvm_source=${LLVM_SOURCE_DIR:-"$project_root/llvm-project"}
llvm_build=${LLVM_BUILD_DIR:-"$llvm_source/build-nosuz16"}
if [[ $# != 2 ]]; then
  echo "Usage: $0 INPUT.c OUTPUT.hex|OUTPUT.bin" >&2
  exit 1
fi
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
"$llvm_build/bin/clang" --target=nosuz16 -ffreestanding -fno-builtin \
  -O2 -S -emit-llvm -I "$project_root/llvm-nosuz16/include" \
  "$1" -o "$temporary/program.ll"
"$project_root/llvm-nosuz16/scripts/compile.sh" "$temporary/program.ll" "$2"
