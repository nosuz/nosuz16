#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
llvm_source=${LLVM_SOURCE_DIR:-"$project_root/llvm-project"}
llvm_build=${LLVM_BUILD_DIR:-"$llvm_source/build-nosuz16"}
cmake -S "$llvm_source/llvm" -B "$llvm_build" -G Ninja \
 -DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_ASSERTIONS=ON \
 -DLLVM_USE_LINKER=lld -DLLVM_PARALLEL_LINK_JOBS=1 \
 -DLLVM_TARGETS_TO_BUILD= -DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=Nosuz16 \
 -DLLVM_ENABLE_PROJECTS= -DLLVM_INCLUDE_TESTS=ON
cmake --build "$llvm_build" --parallel "${LLVM_BUILD_JOBS:-2}" \
 --target llc llvm-mc llvm-objdump llvm-tblgen FileCheck count not llvm-config llvm-readobj opt TargetParserTests
