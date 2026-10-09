#!/usr/bin/env bash
set -euo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
llvm_source=${LLVM_SOURCE_DIR:-"$project_root/llvm-project"}
base=$(cat "$project_root/llvm-nosuz16/LLVM_BASE_REVISION")
patch="$project_root/llvm-nosuz16/patches/0001-nosuz16-backend.patch"
if [[ $(git -C "$llvm_source" rev-parse HEAD) != "$base" ]]; then
  echo "Expected LLVM revision $base in $llvm_source" >&2
  exit 1
fi
if git -C "$llvm_source" apply --reverse --check "$patch" 2>/dev/null; then
  echo "Nosuz16 patch is already applied."
  exit 0
fi
git -C "$llvm_source" apply --check "$patch"
git -C "$llvm_source" apply "$patch"
echo "Applied Nosuz16 backend to $llvm_source"
