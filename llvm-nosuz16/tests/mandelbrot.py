#!/usr/bin/env python3
"""Compare the Nosuz16 demo with an independent floating-point benchmark."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def reference():
    rows = []
    for y in range(-12, 13):
        row = ''
        for x in range(-39, 40):
            cx, cy = x * 0.0458, y * 0.08333
            a, b = cx, cy
            character = ' '
            for iteration in range(16):
                a, b = a * a - b * b + cx, 2 * a * b + cy
                if a * a + b * b > 4:
                    character = '0123456789ABCDEF'[iteration]
                    break
            row += character
        rows.append(row)
    return '\n'.join(rows) + '\n'


def main():
    emulator = Path(os.environ.get('NOSUZ16_EMULATOR') or shutil.which('nosuz16')
                    or ROOT / 'nosuz16/target/release/nosuz16')
    if not emulator.is_file():
        raise RuntimeError('Build the release emulator with cargo build --release '
                           '--manifest-path nosuz16/Cargo.toml, or set NOSUZ16_EMULATOR')
    with tempfile.TemporaryDirectory(prefix='nosuz16-mandelbrot-') as temporary:
        image = Path(temporary) / 'mandelbrot.bin'
        subprocess.run([ROOT / 'llvm-nosuz16/scripts/compile-c.sh',
                        ROOT / 'llvm-nosuz16/examples/mandelbrot.c', image],
                       check=True, timeout=120)
        # The full-grid fixed-point demo takes about 133.9 million instructions.
        # Allow compiler variation while catching a return to the old workload.
        result = subprocess.run([emulator, '--dump', '--max-steps', '200000000', image],
                                capture_output=True, text=True, check=True, timeout=120)
        expected = reference()
        assert result.stdout == expected, 'Demo differs from the floating-point reference'
        sample = (ROOT / 'llvm-nosuz16/examples/mandelbrot.txt').read_text()
        assert sample == expected, 'Saved sample output is stale'
        assert 'r1=0000' in result.stderr and 'r6=FF00' in result.stderr, result.stderr
        assert 'halted=true faulted=false' in result.stderr, result.stderr
        print('PASS Mandelbrot: all 79x25 pixels match the benchmark formula; '
              'return value zero and stack restored')


if __name__ == '__main__':
    main()
