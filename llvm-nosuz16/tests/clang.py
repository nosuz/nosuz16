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
                       '__NOSUZ16__ 1', '__NOSUZ16_SCALAR_C__ 1',
                       '__NOSUZ16_BYTE_ADDRESSABLE__ 1', '__NOSUZ16_SPEC_VERSION__ 205'):
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
        memory = directory / 'memory.o'
        run([CLANG, *FLAGS, '-O2', '-c', ROOT / 'llvm-nosuz16/runtime/memory.c',
             '-o', memory])
        start = directory / 'start.o'
        assemble(STARTUP, start)

        def test(name, source, expected, output='', input_text='', extra_objects=()):
            c = directory / f'{name}.c'
            c.write_text(source)
            for level in (0, 1, 2):
                ir = directory / f'{name}-{level}.ll'
                run([CLANG, *FLAGS, f'-O{level}', '-S', '-emit-llvm', c, '-o', ir])
                # Both LLVM codegen levels and assembly/direct-object paths.
                execute(directory, f'c-{name}-O{level}', ir.read_text(), expected,
                        runtime=runtime, startup=STARTUP, output=output, input_text=input_text,
                        extra_objects=(console, memory, *extra_objects))
                asm = directory / f'{name}-{level}.s'
                object_file = directory / f'{name}-{level}.o'
                assembled = directory / f'{name}-{level}-assembled.o'
                run([CLANG, *FLAGS, f'-O{level}', '-S', c, '-o', asm])
                assemble(asm.read_text(), assembled)
                run([CLANG, *FLAGS, f'-O{level}', '-c', c, '-o', object_file])
                for obj in (object_file, assembled):
                    image = directory / 'program.bin'
                    run(['python3', IMAGE, start, obj, runtime, console, memory,
                         *extra_objects, '-o', image])
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

        test('byte-storage', '''#include "nosuz16.h"
int main(void) {
  volatile unsigned char *p = (volatile unsigned char *)0x4000u;
  nosuz16_stw(0x4000u, 0xabcd);
  unsigned int read = *p;
  *p = 255;
  return read + nosuz16_ldw(0x4000u);
}''', 44236)
        test('byte-io', '''#include "nosuz16.h"
int main(void) {
  nosuz16_stw(NOSUZ16_VIDEO_MODE,0x1234u);
  nosuz16_stb(NOSUZ16_VIDEO_MODE+1u,0xabu);
  (void)nosuz16_ldb(NOSUZ16_UART_TXRX+1u);
  unsigned int ready=nosuz16_ldb(NOSUZ16_UART_STATUS);
  unsigned int byte=nosuz16_ldb(NOSUZ16_UART_TXRX);
  nosuz16_stb(NOSUZ16_UART_TXRX,byte);
  return ready==3u && nosuz16_ldw(NOSUZ16_VIDEO_MODE)==0xab34u &&
         nosuz16_ldb(NOSUZ16_VIDEO_MODE)==0x34u &&
         nosuz16_ldb(NOSUZ16_VIDEO_MODE+1u)==0xabu;
}''', 1, 'Q', 'Q')
        test('int-storage', '''#include "nosuz16.h"
int main(void) {
  volatile unsigned int *p = (volatile unsigned int *)0x4000u;
  *p = 0xabcd;
  unsigned char *bytes = (unsigned char *)p;
  return (*p == 0xabcd && bytes[0] == 0xcd && bytes[1] == 0xab &&
          nosuz16_ldw(0x4000u) == 0xabcd &&
          (unsigned int)(p + 1) == 0x4002u);
}''', 1)
        test('high-address', '''#include "nosuz16.h"
int main(void) {
  volatile unsigned char *p = (volatile unsigned char *)0xe000u;
  p[0] = 255; p[1] = 128;
  return p[0] + p[1] + ((unsigned int)(p + 1) == 0xe001u);
}''', 384)
        # Assembly observes all 16 ABI bits, avoiding truncation by a C callee.
        char_abi = directory / 'char-abi.o'
        assemble('''.text
.globl inspect_char_args
inspect_char_args:
 add r1,r2
 add r1,r3
 ld r2,[r6+0]
 add r1,r2
 ret
.globl inspect_char_return
inspect_char_return:
 addi r6,-2
 st r7,[r6+0]
 lcall negative_char
 ld r7,[r6+0]
 addi r6,2
 ret
''', char_abi)
        test('char-abi', '''__attribute__((noinline)) signed char byte(signed char v) { return v; }
__attribute__((noinline)) unsigned char positive(unsigned char v) { return v; }
__attribute__((noinline)) signed char negative_char(void) { volatile signed char v=-1; return v; }
int inspect_char_args(signed char, unsigned char, _Bool, signed char);
int inspect_char_return(void);
int main(void) { volatile signed char a=-1; volatile unsigned char b=255;
 return byte(a) + positive(b) + inspect_char_args(a,b,1,-128) + inspect_char_return();
}''', 380, extra_objects=(char_abi,))
        test('pointer-abi', '''__attribute__((noinline)) int *select(int *a,int *b,int *c,int *d) { return d; }
int main(void) { int a=1,b=2,c=3,d=41; int *p=select(&a,&b,&c,&d); ++*p;
 return *p + a + b + c; }''', 48)
        test('array-stack', '''__attribute__((noinline)) int sum(int *p,int n) {
 int s=0; for(int i=0;i<n;++i) s+=p[i]; return s;
}
int main(void) { int a[6]={1,2,3,4,5,6}; return sum(a,6); }''', 21)
        test('struct', '''struct S { unsigned char a; int b; char c; };
__attribute__((noinline)) int inspect(struct S *p) {
 p->a=255; p->b=-123; p->c=7;
 return p->a+p->b+p->c + sizeof(struct S) + ((char *)&p->b-(char *)p);
}
int main(void) { struct S s; return inspect(&s); }''', 147)
        test('packed', '''struct __attribute__((packed)) S { char a; int b; char c; };
__attribute__((noinline)) int inspect(struct S *p) { p->a=1;p->b=300;p->c=2;
 return p->a+p->b+p->c+sizeof(struct S)+((char *)&p->b-(char *)p); }
int main(void) { struct S s; return inspect(&s); }''', 308)
        test('globals', '''#include "nosuz16.h"
char text[]="Hello";
int values[3]={1,-2,300};
char *message=text+1;
int *number=values+2;
struct S {char a;int b;char c;} state={3,100,4};
int main(void) { values[0]=42; state.b+=2;
 return printf("%s",message) + *number + values[0] + state.a+state.b+state.c; }
''', 455, 'ello')
        test('pointer-storage', '''#include "nosuz16.h"
int main(void) { volatile unsigned char **p=(volatile unsigned char **)0x4000u;
 *p=(volatile unsigned char *)0xe000u; **p=42;
 return **p + nosuz16_ldw(0x4000u); }
''', 57386)
        test('large-stack', '''__attribute__((noinline)) int fill(char *p) { p[0]=3;p[127]=4;return p[0]+p[127]; }
int main(void) { char buffer[128]; return fill(buffer); }''', 7)
        test('memory-intrinsics', '''#include "nosuz16.h"
int main(void) { char buffer[12];
 __builtin_memset(buffer,0,sizeof(buffer));
 __builtin_memcpy(buffer,"abcdef",7);
 __builtin_memmove(buffer+1,buffer,6);
 return printf("%s",buffer); }
''', 7, 'aabcdef')
        test('bool-memory', '''__attribute__((noinline)) _Bool flip(_Bool *p) { *p=!*p;return *p; }
int main(void) { _Bool b=0; return flip(&b); }''', 1)
        text = 'You typed: Hello\n'
        test('read-line', (ROOT / 'llvm-nosuz16/examples/read-line.c').read_text(),
             len(text), text, 'Hello\n')
        test('struct-copy', '''struct S { char a; int b; char c; };
struct S initial={3,100,4};
__attribute__((noinline)) int copy(struct S *d,struct S *s) {
 *d=*s; return d->a+d->b+d->c;
}
int main(void) { struct S a=initial,b;int n=copy(&b,&a);a.b=0;return n+b.b; }
''', 207)
        test('stack-alignment', '''__attribute__((noinline)) int check(char *p) {
 volatile int n=3; *p=1; return ((unsigned int)&n & 1u)==0u;
}
int main(void) { char a[3]; volatile int n=4;
 return check(a)+(((unsigned int)&n & 1u)==0u); }
''', 2)
        # Symbolic pointer initializers must relocate at a nonzero load address.
        relocated = directory / 'relocated.bin'
        run(['python3', IMAGE, '--origin', '0x100', start, directory / 'globals-2.o',
             runtime, console, memory, '-o', relocated])
        result = run([EMU, '--dump', '--load-address', '0x100', relocated])
        assert result.stdout == 'ello' and 'r1=01C7' in result.stderr, result
        assert 'r4=1234 r5=ABCD r6=FF00' in result.stderr, result
        assert 'halted=true faulted=false' in result.stderr, result
        print('PASS global pointer relocation at nonzero origin')

        for name, source, diagnostic in (
            ('memory', 'int main(void) { return *(volatile long *)0x4000u; }','memory values'),
            ('overaligned', 'int main(void) { _Alignas(4) volatile int n=1; return n; }', 'stack alignment'),
            ('vla', 'int main(void) { volatile int n=3; volatile char a[n]; a[0]=1; return a[0]; }', 'dynamic'),
            ('wide', 'long wide(long a) { return a+1; }','return must'),
            ('varargs', 'int variable(int a, ...) { return a; }','variadic'),
            ('float', 'float number(float a) { return a+1.0f; }','return must'),
            ('printf-width', '#include "nosuz16.h"\nint main(void) { return printf("%04d", 1); }', 'unsupported conversion'),
            ('printf-float', '#include "nosuz16.h"\nint main(void) { return printf("%f", 1.0); }', 'unsupported conversion'),
            ('printf-missing', '#include "nosuz16.h"\nint main(void) { return printf("%d"); }', 'missing conversion argument'),
            ('printf-dynamic', '#include "nosuz16.h"\nint main(void) { return printf((const char *)0x4000u, 1); }', 'format must be a constant'),
            ('printf-string', '#include "nosuz16.h"\nint main(void) { return printf("%s", 1); }', '%s requires a character pointer'),
            ('printf-wide', '#include "nosuz16.h"\nint main(void) { return printf("%d", 1L); }', 'integer conversion arguments must be i16'),
            ('printf-incomplete', '#include "nosuz16.h"\nint main(void) { return printf("abc%"); }', 'incomplete conversion')):
            c=directory/f'{name}.c';c.write_text(source)
            failure=run([CLANG,*FLAGS,'-O2','-c',c,'-o',directory/'rejected.o'],success=False)
            assert diagnostic in failure.stderr,failure.stderr
        print('PASS unsupported C diagnostics')
    print('All Nosuz16 Clang execution tests passed.')


if __name__ == '__main__':
    main()
