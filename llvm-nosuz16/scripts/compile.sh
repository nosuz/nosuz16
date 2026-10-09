#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
llvm_source=${LLVM_SOURCE_DIR:-"$project_root/llvm-project"}
llvm_build=${LLVM_BUILD_DIR:-"$llvm_source/build-nosuz16"}
if [[ $# != 2 ]]; then
  echo "Usage: $0 INPUT.ll OUTPUT.hex|OUTPUT.bin" >&2
  exit 1
fi
temporary=$(mktemp -d)
trap 'rm -rf -- "$temporary"' EXIT
"$llvm_build/bin/llc" -mtriple=nosuz16 -verify-machineinstrs -filetype=asm \
  "$1" -o "$temporary/program.s"
"$llvm_build/bin/llvm-mc" -triple=nosuz16 -filetype=obj \
  "$temporary/program.s" -o "$temporary/program.o"
"$llvm_build/bin/llvm-mc" -triple=nosuz16 -filetype=obj \
  "$project_root/llvm-nosuz16/runtime/start.s" -o "$temporary/start.o"
"$llvm_build/bin/llc" -mtriple=nosuz16 -verify-machineinstrs -filetype=obj \
  "$project_root/llvm-nosuz16/runtime/arithmetic.ll" -o "$temporary/arithmetic.o"
python3 "$project_root/llvm-nosuz16/scripts/image.py" \
  "$temporary/start.o" "$temporary/program.o" "$temporary/arithmetic.o" -o "$2"
