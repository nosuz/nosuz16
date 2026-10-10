#!/usr/bin/env python3
"""Smoke-test an installed SDK without LLVM sources, Cargo, or build tools."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sdk_root', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[2])
    root = parser.parse_args().sdk_root.resolve()
    tools = root / 'toolchain/bin'
    support = root / 'llvm-nosuz16'
    env = dict(os.environ, LLVM_BUILD_DIR=str(root / 'toolchain'))

    def run(args):
        result = subprocess.run([str(arg) for arg in args], env=env,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise AssertionError(f'{args}\n{result.stdout}\n{result.stderr}')
        return result

    for tool in ('clang', 'llc', 'llvm-mc', 'opt', 'llvm-objdump', 'llvm-readobj'):
        run([tools / tool, '--version'])

    with tempfile.TemporaryDirectory(prefix='nosuz16-sdk-') as temporary:
        directory = Path(temporary)
        cases = [
            ('hello.ll', 'hex', '', 'Hi\n', 42),
            ('hello.c', 'bin', '', 'Hi\n', 42),
            ('read-line.c', 'bin', 'Hello\n', 'You typed: Hello\n', 17),
        ]
        for name, extension, uart, expected, return_value in cases:
            image = directory / f'{name}.{extension}'
            script = 'compile.sh' if name.endswith('.ll') else 'compile-c.sh'
            run([support / 'scripts' / script, support / 'examples' / name, image])
            result = run([tools / 'nosuz16', '--dump', '--uart-input', uart, image])
            assert result.stdout == expected, (name, result.stdout)
            assert f'r1={return_value:04X}' in result.stderr, result.stderr
            assert 'r6=FF00' in result.stderr, result.stderr
            assert 'halted=true faulted=false' in result.stderr, result.stderr
            print(f'PASS installed SDK: {name} -> {extension}')

        # Clang must find its installed resource headers after relocation.
        source = directory / 'headers.c'
        source.write_text('''#include <stddef.h>
#include <stdbool.h>
#include "nosuz16.h"
int main(void) {
  volatile unsigned int *p = (volatile unsigned int *)0x4000u;
  *p = 0x1234u;
  volatile unsigned char *bytes = (volatile unsigned char *)p;
  bool packed = *p == 0x1234u && bytes[0] == 0x34u && bytes[1] == 0x12u;
  return putc(packed && sizeof(size_t) == 2 ? 'K' : 'X');
}
''')
        image = directory / 'headers.bin'
        run([support / 'scripts/compile-c.sh', source, image])
        result = run([tools / 'nosuz16', '--dump', image])
        assert result.stdout == 'K' and 'r1=004B' in result.stderr, result
        assert 'r6=FF00' in result.stderr and 'faulted=false' in result.stderr, result.stderr

        # Exercise the retained optimizer and both object inspection tools.
        ir = directory / 'hello.ll'
        run([tools / 'clang', '--target=nosuz16', '-ffreestanding', '-fno-builtin',
             '-I', support / 'include', '-S', '-emit-llvm',
             support / 'examples/hello.c', '-o', ir])
        optimized = directory / 'hello-opt.ll'
        run([tools / 'opt', '-passes=default<O2>', '-S', ir, '-o', optimized])
        obj = directory / 'hello.o'
        run([tools / 'llc', '-mtriple=nosuz16', '-filetype=obj', optimized, '-o', obj])
        disassembly = run([tools / 'llvm-objdump', '--triple=nosuz16', '-d', obj]).stdout
        assert 'st' in disassembly, disassembly
        header = run([tools / 'llvm-readobj', '--file-headers', obj]).stdout
        assert re.search(r'0x205\b', header), header
        print('PASS installed headers, packed memory, optimization, and object inspection')


if __name__ == '__main__':
    main()
