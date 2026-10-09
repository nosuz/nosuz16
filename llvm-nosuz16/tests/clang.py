#!/usr/bin/env python3
"""Verify the experimental Clang scalar frontend against the real CPU."""
from pathlib import Path
import re
import tempfile
from run import ROOT, TOOLS, EMU, IMAGE, STARTUP, execute, run, assemble

CLANG = TOOLS / 'clang'
FLAGS = ['--target=nosuz16', '-ffreestanding', '-fno-builtin',
         '-I', ROOT / 'llvm-nosuz16/include']


def main():
    run(['cargo', 'build', '--manifest-path', ROOT / 'nosuz16/Cargo.toml'])
    macros = run([CLANG, *FLAGS, '-E', '-dM', '-x', 'c', '-'], input='').stdout
    for definition in ('__CHAR_BIT__ 8', '__SIZEOF_INT__ 2', '__SIZEOF_POINTER__ 2',
                       '__NOSUZ16__ 1', '__NOSUZ16_SCALAR_C__ 1'):
        assert '#define ' + definition in macros, definition
    print('PASS Clang target macros')
    with tempfile.TemporaryDirectory(prefix='nosuz16-clang-tests-') as temporary:
        directory = Path(temporary)
        runtime = directory / 'runtime.o'
        run([TOOLS / 'llc', '-mtriple=nosuz16', '-verify-machineinstrs', '-filetype=obj',
             ROOT / 'llvm-nosuz16/runtime/arithmetic.ll', '-o', runtime])
        console = directory / 'console.o'
        run([CLANG, *FLAGS, '-O2', '-c', ROOT / 'llvm-nosuz16/runtime/console.c',
             '-o', console])
        start = directory / 'start.o'
        assemble(STARTUP, start)

        def test(name, source, expected, output='', input_text=''):
            c = directory / f'{name}.c'
            c.write_text(source)
            for level in (1, 2):
                ir = directory / f'{name}-{level}.ll'
                run([CLANG, *FLAGS, f'-O{level}', '-S', '-emit-llvm', c, '-o', ir])
                # Both LLVM codegen levels and assembly/direct-object paths.
                execute(directory, f'c-{name}-O{level}', ir.read_text(), expected,
                        runtime=runtime, startup=STARTUP, output=output, input_text=input_text,
                        extra_objects=(console,))
                asm = directory / f'{name}-{level}.s'
                object_file = directory / f'{name}-{level}.o'
                assembled = directory / f'{name}-{level}-assembled.o'
                run([CLANG, *FLAGS, f'-O{level}', '-S', c, '-o', asm])
                assemble(asm.read_text(), assembled)
                run([CLANG, *FLAGS, f'-O{level}', '-c', c, '-o', object_file])
                for obj in (object_file, assembled):
                    image = directory / 'program.bin'
                    run(['python3', IMAGE, start, obj, runtime, console, '-o', image])
                    result = run([EMU, '--dump', '--max-steps', '1000000',
                                  '--uart-input', input_text, image])
                    assert result.stdout == output, result
                    regs = dict((int(n), int(value, 16)) for n, value in
                                re.findall(r'r([0-7])=([0-9A-F]{4})', result.stderr))
                    assert regs[1] == expected & 65535, (name, level, result.stderr)
                    assert regs[4] == 0x1234 and regs[5] == 0xabcd and regs[6] == 0xff00, result.stderr
                    assert 'halted=true faulted=false' in result.stderr, result.stderr
            print(f'PASS direct Clang assembly/object: {name}')

        test('hello', (ROOT / 'llvm-nosuz16/examples/hello.c').read_text(), 42, 'Hi\n')
        test('echo', (ROOT / 'llvm-nosuz16/examples/echo.c').read_text(), 65, 'A', 'A')
        test('console', '''#include "nosuz16.h"
int main(void) {
  int zero = putc(0);
  int byte = getc();
  int sent = putc(0x142);
  int high = getc();
  int next = getc();
  return zero + byte + sent + high + next + putc(-191);
}''', 561, '\x00BA', 'B\u00e9')
        test('discard-getc', '''#include "nosuz16.h"
int main(void) { (void)getc(); return putc(getc()); }
''', 66, 'B', 'AB')
        # Empty input must keep polling, rather than return a fabricated NUL.
        waiting = run([EMU, '--dump', '--max-steps', '1000', directory / 'program.bin'],
                      success=False)
        assert waiting.stdout == '' and 'halted=false faulted=false' in waiting.stderr, waiting
        text = 'Hello Nosuz16! value=-123 hex=BEEF %\n'
        test('printf-example', (ROOT / 'llvm-nosuz16/examples/printf.c').read_text(),
             len(text), text)
        text = '-32768 -1 0 32767 65535 ffff BEEF 177777 A word %\n'
        test('printf-conversions', '''#include "nosuz16.h"
__attribute__((noinline)) int show(int value, unsigned int bits) {
  return printf("%d %i %d %d %u %x %X %o %c %s %%\\n",
                value, -1, 0, 32767, bits, bits, 0xbeefu, bits, 0x141, "word");
}
int main(void) { return show(-32768, 65535u); }
''', len(text), text)
        test('printf-empty', '''#include "nosuz16.h"
int main(void) { return printf(""); }
''', 0)
        test('printf-evaluation', '''#include "nosuz16.h"
int main(void) { return printf("%c", getc()); }
''', 1, 'Z', 'Z')
        test('printf-nul', '''#include "nosuz16.h"
int main(void) { return printf("x%c%s", 0, "y\\0ignored"); }
''', 3, 'x\x00y')
        test('math', '''__attribute__((noinline)) unsigned int mix(unsigned int a,unsigned int b) {
 return ((a+b)^0x55aau)*7u;
}
int main(void) { return mix(10000u,22222u)/123u + 10u; }''',
             (((10000+22222)^0x55aa)*7 & 65535)//123+10)
        test('abs', '''__attribute__((noinline)) int absolute(int a) { return a<0?-a:a; }
int main(void) { return absolute(-12345); }''', 12345)
        test('char', '''__attribute__((noinline)) int byte(int a) { signed char b=(signed char)a; return b+50; }
int main(void) { return byte(255); }''', 49)
        test('loop', '''#include "nosuz16.h"
__attribute__((noinline)) void output(int n) { for(int i=0;i<n;i++) nosuz16_stw(NOSUZ16_UART_TXRX,65u); }
int main(void) { output(3); return 42; }''', 42, 'AAA')
        test('io', '''#include "nosuz16.h"
int main(void) {
 nosuz16_stw(0x4000u,1234u);
 unsigned int value=nosuz16_ldw(0x4000u);
 (void)nosuz16_ldw(NOSUZ16_UART_TXRX);
 unsigned int byte=nosuz16_ldw(NOSUZ16_UART_TXRX);
 nosuz16_stw(NOSUZ16_UART_TXRX,byte);
 return value+byte;
}''',1300,'B','AB')
        count=70
        arguments=','.join(f'int a{i}' for i in range(count))
        values=','.join(str(i+1) for i in range(count))
        source=f'__attribute__((noinline)) int many({arguments}) {{ return '+'+'.join(f'a{i}' for i in range(count))+f'; }}\nint main(void) {{ return many({values}); }}'
        test('stack-args',source,count*(count+1)//2)

        for name, source, diagnostic in (
            ('memory', 'int main(void) { return *(volatile int *)0x4000u; }','generic memory'),
            ('wide', 'long wide(long a) { return a+1; }','return must'),
            ('varargs', 'int variable(int a, ...) { return a; }','variadic'),
            ('float', 'float number(float a) { return a+1.0f; }','return must'),
            ('printf-width', '#include "nosuz16.h"\nint main(void) { return printf("%04d", 1); }', 'unsupported conversion'),
            ('printf-float', '#include "nosuz16.h"\nint main(void) { return printf("%f", 1.0); }', 'unsupported conversion'),
            ('printf-missing', '#include "nosuz16.h"\nint main(void) { return printf("%d"); }', 'missing conversion argument'),
            ('printf-dynamic', '#include "nosuz16.h"\nint main(void) { return printf((const char *)0x4000u, 1); }', 'format must be a constant'),
            ('printf-string', '#include "nosuz16.h"\nint main(void) { return printf("%s", (const char *)0x4000u); }', '%s requires a constant'),
            ('printf-wide', '#include "nosuz16.h"\nint main(void) { return printf("%d", 1L); }', 'integer conversion arguments must be i16'),
            ('printf-incomplete', '#include "nosuz16.h"\nint main(void) { return printf("abc%"); }', 'incomplete conversion')):
            c=directory/f'{name}.c';c.write_text(source)
            failure=run([CLANG,*FLAGS,'-O2','-c',c,'-o',directory/'rejected.o'],success=False)
            assert diagnostic in failure.stderr,failure.stderr
        print('PASS unsupported C diagnostics')
    print('All Nosuz16 Clang execution tests passed.')


if __name__ == '__main__':
    main()
