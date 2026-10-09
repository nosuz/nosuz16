#!/usr/bin/env python3
"""Compile real LLVM IR, assemble/link it, and check execution in the Rust CPU."""
import argparse
import os
from pathlib import Path
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(os.environ.get('LLVM_SOURCE_DIR', ROOT / 'llvm-project'))
BUILD = Path(os.environ.get('LLVM_BUILD_DIR', SOURCE / 'build-nosuz16'))
TOOLS = BUILD / 'bin'
EMU = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'nosuz16/target')) / 'debug/nosuz16'
IMAGE = ROOT / 'llvm-nosuz16/scripts/image.py'


def run(args, *, input=None, success=True):
    result = subprocess.run([str(arg) for arg in args], input=input, text=True,
                            capture_output=True, timeout=120)
    if success and result.returncode:
        raise AssertionError(f"{' '.join(map(str, args))}\n{result.stderr}")
    if not success and not result.returncode:
        raise AssertionError(f'expected failure: {args}')
    return result


def assemble(source, target):
    run([TOOLS / 'llvm-mc', '-triple=nosuz16', '-filetype=obj', '-o', target], input=source)


def execute(directory, name, ir, expected, runtime=None, output='', input_text='', startup=None,
            extra_objects=()):
    ll = directory / f'{name}.ll'
    ll.write_text(ir)
    start = directory / 'start.o'
    assemble(startup or (ROOT / 'llvm-nosuz16/runtime/start.s').read_text(), start)
    for level in (0, 2):
        asm, obj, direct = (directory / f'{name}-{level}.{suffix}' for suffix in ('s', 'o', 'direct.o'))
        run([TOOLS / 'llc', '-mtriple=nosuz16', f'-O{level}', '-verify-machineinstrs', ll, '-o', asm])
        assemble(asm.read_text(), obj)
        # Exercise both assembly round trips and direct object emission.
        run([TOOLS / 'llc', '-mtriple=nosuz16', f'-O{level}', '-verify-machineinstrs',
             '-filetype=obj', ll, '-o', direct])
        for object_file in (obj, direct):
            image = directory / f'{name}-{level}.bin'
            run(['python3', IMAGE, start, object_file, *([runtime] if runtime else []),
                 *extra_objects, '-o', image])
            result = run([EMU, '--dump', '--max-steps', '1000000', '--uart-input', input_text, image])
            assert result.stdout == output, (name, level, result.stdout, output)
            registers = dict((int(index), int(value, 16)) for index, value in
                             re.findall(r'r([0-7])=([0-9A-F]{4})', result.stderr))
            assert registers[1] == (expected & 0xffff), (name, level, registers, expected)
            assert registers[0] == 0 and registers[6] == 0xff00, (name, level, registers)
            assert registers[4] == 0x1234 and registers[5] == 0xabcd, (name, level, registers)
            assert 'halted=true faulted=false' in result.stderr, result.stderr
    print(f'PASS {name} (O0/O2, assembly/direct object)')


STARTUP = '.text\n.globl _start\n_start:\nli r6,65280\nli r4,4660\nli r5,43981\nlcall main\nhalt\n'
DECLS = 'declare i16 @llvm.nosuz16.ldw(i16)\ndeclare void @llvm.nosuz16.stw(i16, i16)\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mc-only',action='store_true')
    options=parser.parse_args()
    run(['cargo', 'test', '--manifest-path', ROOT / 'nosuz16/Cargo.toml'])
    run(['cargo', 'build', '--manifest-path', ROOT / 'nosuz16/Cargo.toml'])
    with tempfile.TemporaryDirectory(prefix='nosuz16-tests-') as temporary:
        directory = Path(temporary)
        # Independent expected words for every native opcode and HALT.
        source = '''add r1,r2
sub r1,r2
addc r1,r2
subc r1,r2
and r1,r2
or r1,r2
xor r1,r2
sll r1
srl r1
asr r1
addi r1,-32
ld r1,[r2+31]
st r1,[r2-32]
beq r1,r2,-32
bne r1,r2,31
blt r1,r2,-1
jal r7,-256
jalr r7,r7,31
halt
'''
        native = directory / 'native.o'
        assemble(source, native)
        binary = directory / 'native.bin'
        run(['python3', IMAGE, native, '-o', binary])
        words = struct.unpack('<19H', binary.read_bytes())
        assert words == (0x280,0x281,0x282,0x283,0x284,0x285,0x286,0x207,0x208,0x209,
                         0x1260,0x229f,0x32a0,0x42a0,0x529f,0x62bf,0x7f00,0x8fdf,0xf000), words
        decoded = run([TOOLS / 'llvm-mc', '-triple=nosuz16', '--disassemble'],
                      input='\n'.join(f'0x{word & 255:02x} 0x{word >> 8:02x}' for word in words))
        assert 'addc' in decoded.stdout and 'halt' in decoded.stdout, decoded.stdout
        print('PASS native encodings and decoding')
        assemble('mov r2,r2\nmov r1,r2\ncmp r1,r2,r3\nnop\nsubi r1,32\nret\n', native)
        run(['python3', IMAGE, native, '-o', binary])
        assert struct.unpack('<9H', binary.read_bytes()) == (
            0x1480,0x246,0x280,0x6c6,0x640,0x681,0x7000,0x1260,0x81c0)
        print('PASS alias encodings')
        for invalid in ('addi r1,32','addi r1,-33','jal r1,256','jal r1,-257',
                        'subi r1,-32','cmp r1,r2,r0','cmp r1,r2,r1','add r8,r1','ld r1,[r2+32]'):
            run([TOOLS / 'llvm-mc', '-triple=nosuz16', '-filetype=obj', '-o', native], input=invalid+'\n', success=False)
        bad = run([TOOLS / 'llvm-mc', '-triple=nosuz16', '--disassemble'], input='0x00 0x90\n0x01 0xf0\n0x0a 0x00\n')
        assert bad.stderr.count('invalid instruction encoding') == 3, bad.stderr
        print('PASS invalid encodings and assembly operands')
        # Link symbolic code/data at a nonzero CPU word address.
        assemble('.text\n.globl _start\n_start:\nli r6,65280\nlcall main\nhalt\nmain:\nli r1,42\nret\n.data\n.short main\n',native)
        run(['python3',IMAGE,native,'--origin','0x100','-o',binary])
        relocated=run([EMU,'--dump','--load-address','0x100',binary])
        assert 'r1=002A' in relocated.stderr and 'r6=FF00' in relocated.stderr,relocated.stderr
        assert struct.unpack_from('<H',binary.read_bytes(),len(binary.read_bytes())-2)[0]==0x144
        assemble('beq r0,r0,forward\nnop\nforward: bne r0,r0,forward\n',native)
        run(['python3',IMAGE,native,'-o',binary])
        assert struct.unpack('<3H',binary.read_bytes())==(0x4001,0x7000,0x503f)
        assemble('.text\n.byte 0\n',native)
        assert 'aligned words' in run(['python3',IMAGE,native,'-o',binary],success=False).stderr
        assemble('.text\n.space 130562\n',native)
        assert 'boundary' in run(['python3',IMAGE,native,'-o',binary],success=False).stderr
        print('PASS MC fixups, relocated word symbols, and image bounds')
        if options.mc_only:
            return
        def test(name, ir, expected, **kwargs):
            execute(directory, name, ir, expected, startup=STARTUP, **kwargs)
        test('constant', 'define i16 @main() { ret i16 -1 }', 65535)
        test('hello', (ROOT / 'llvm-nosuz16/examples/hello.ll').read_text(), 42, output='Hi\n')
        test('void-call', DECLS+"define void @put(i16 %c) { call void @llvm.nosuz16.stw(i16 -256,i16 %c) ret void }\ndefine i16 @main() { call void @put(i16 67) ret i16 42 }",42,output='C')
        test('arithmetic', '''define i16 @mix(i16 %a,i16 %b) {
 %sum=add i16 %a,%b
 %sub=sub i16 %sum,17
 %and=and i16 %sub,32767
 %or=or i16 %and,64
 %xor=xor i16 %or,21930
 ret i16 %xor
}
define i16 @main() {
 %v=call i16 @mix(i16 32760,i16 2345)
 ret i16 %v
}''', (((32760+2345-17)&32767)|64)^21930)
        for condition in ('eq','ne','slt','sle','sgt','sge','ult','ule','ugt','uge'):
            pairs = [(0,0),(-32768,32767),(32767,-32768),(-1,0),(0,-1),(7,8),(8,7)]
            helper = f'''define i16 @compare(i16 %a,i16 %b) {{
 %c=icmp {condition} i16 %a,%b
 %v=select i1 %c,i16 123,i16 45
 ret i16 %v
}}
'''
            body, expected, previous = [], 0, '0'
            for index,(a,b) in enumerate(pairs):
                body.extend([f'%r{index}=call i16 @compare(i16 {a},i16 {b})',
                             f'%s{index}=add i16 {previous},%r{index}'])
                previous=f'%s{index}'
                aa,bb = (a&65535,b&65535) if condition.startswith('u') else (a,b)
                op=condition.lstrip('su')
                result={'eq':aa==bb,'ne':aa!=bb,'lt':aa<bb,'le':aa<=bb,'gt':aa>bb,'ge':aa>=bb}[op]
                expected += 123 if result else 45
            test('compare-'+condition, helper+'define i16 @main() {\n'+'\n'.join(body)+f'\nret i16 {previous}\n}}', expected)
        for operation, expected in (('shl',0x8123<<7),('lshr',0x8123>>7),('ashr',(-32477)>>7)):
            test('shift-'+operation, f'''define i16 @shift(i16 %a,i16 %n) {{
 %v={operation} i16 %a,%n
 ret i16 %v
}}
define i16 @main() {{
 %a=call i16 @shift(i16 -32477,i16 7)
 %b=call i16 @shift(i16 123,i16 0)
 %v=add i16 %a,%b
 ret i16 %v
}}''', expected+123)
        test('subword', "define i16 @calc(i16 %a) { %b=trunc i16 %a to i8 %c=add i8 %b,50 %v=sext i8 %c to i16 ret i16 %v }\ndefine i16 @main() { %v=call i16 @calc(i16 120) ret i16 %v }", -86)
        test('loop', '''define i16 @sum(i16 %limit) {
entry:
 br label %loop
loop:
 %i=phi i16 [0,%entry],[%next,%loop]
 %total=phi i16 [0,%entry],[%sum,%loop]
 %sum=add i16 %total,%i
 %next=add i16 %i,1
 %done=icmp eq i16 %next,%limit
 br i1 %done,label %exit,label %loop
exit:
 ret i16 %sum
}
define i16 @main() { %v=call i16 @sum(i16 100) ret i16 %v }''', 4950)
        word_io=DECLS+'''define i16 @main() {
 call void @llvm.nosuz16.stw(i16 16384,i16 -1234)
 %mem=call i16 @llvm.nosuz16.ldw(i16 16384)
 %discard=call i16 @llvm.nosuz16.ldw(i16 -256)
 %rx=call i16 @llvm.nosuz16.ldw(i16 -256)
 call void @llvm.nosuz16.stw(i16 -256,i16 %rx)
 %v=add i16 %mem,%rx
 ret i16 %v
}'''
        test('word-io', word_io, -1234+66, output='B', input_text='AB')
        mmio_source=directory/'mmio-source.ll';mmio_source.write_text(word_io)
        mmio_optimized=directory/'mmio-optimized.ll'
        run([TOOLS/'opt','-mtriple=nosuz16','-passes=default<O2>','-S',mmio_source,'-o',mmio_optimized])
        test('optimized-word-io',mmio_optimized.read_text(),-1234+66,output='B',input_text='AB')
        # More than three args plus a frame exceeding the six-bit word offset.
        count=70
        args=','.join(f'i16 %a{i}' for i in range(count))
        lines=[];previous='%a0'
        for i in range(1,count):
            lines.append(f'%s{i}=add i16 {previous},%a{i}');previous=f'%s{i}'
        helper='define i16 @many('+args+') {\n'+'\n'.join(lines)+f'\nret i16 {previous}\n}}\n'
        main='define i16 @main() { %v=call i16 @many('+','.join(f'i16 {i+1}' for i in range(count))+') ret i16 %v }'
        test('large-frame-call', helper+main, count*(count+1)//2)
        stores=[f'call void @llvm.nosuz16.stw(i16 {16384+i},i16 {i+1})' for i in range(20)]
        loads=[f'%v{i}=call i16 @llvm.nosuz16.ldw(i16 {16384+i})' for i in range(20)]
        sums=[];previous='%v0'
        for i in range(1,20):
            sums.append(f'%s{i}=add i16 {previous},%v{i}');previous=f'%s{i}'
        test('spills', DECLS+'define i16 @main() {\n'+'\n'.join(stores+loads+sums)+f'\nret i16 {previous}\n}}',210)
        runtime=directory/'arithmetic.o'
        run([TOOLS/'llc','-mtriple=nosuz16','-verify-machineinstrs','-filetype=obj',
             ROOT/'llvm-nosuz16/runtime/arithmetic.ll','-o',runtime])
        for op,a,b,expected in (('mul',-1234,5678,-1234*5678),('udiv',65535,1,65535),
                               ('udiv',65535,32769,1),('urem',65535,32769,32766),
                               ('sdiv',-32768,7,-4681),('srem',-32768,7,-1),
                               ('sdiv',12345,-123,-100),('srem',12345,-123,45)):
            test(f'runtime-{op}-{a}-{b}',f"define i16 @calc(i16 %a,i16 %b) {{ %v={op} i16 %a,%b ret i16 %v }}\ndefine i16 @main() {{ %v=call i16 @calc(i16 {a},i16 {b}) ret i16 %v }}",expected,runtime=runtime)
        test('constant-divrem', 'define i16 @calc(i16 %a) { %q=udiv i16 %a,7 %r=urem i16 %a,7 %v=add i16 %q,%r ret i16 %v }\ndefine i16 @main() { %v=call i16 @calc(i16 -1) ret i16 %v }',65535//7+65535%7,runtime=runtime)
        for name, ir, diagnostic in (
            ('atomic', 'define i16 @main() { %v=load atomic i16,ptr null monotonic,align 2 ret i16 %v }','atomic memory'),
            ('indirect', 'define i16 @main() { %v=call i16 null() ret i16 %v }','indirect calls'),
            ('wide', 'define i32 @main() { ret i32 1 }','return must'),
            ('varargs', 'define i16 @main(...) { ret i16 1 }','variadic'),
            ('float', 'define float @main() { ret float 1.0 }','return must'),
            ('float-operand', 'define i16 @main() { %v=fptosi float 1.0 to i16 ret i16 %v }','unsupported operand')):
            ll=directory/f'reject-{name}.ll';ll.write_text(ir)
            result=run([TOOLS/'llc','-mtriple=nosuz16',ll,'-o',directory/'reject.s'],success=False)
            assert diagnostic in result.stderr, result.stderr
        print('PASS unsupported IR diagnostics')
        undefined=directory/'undefined.o';assemble('lcall missing\nhalt\n',undefined)
        assert 'undefined symbol' in run(['python3',IMAGE,undefined,'-o',binary],success=False).stderr
        result=run([TOOLS/'llvm-mc','-triple=nosuz16','-filetype=obj','-o',undefined],input='beq r0,r0,far\n.space 128\nfar: halt\n',success=False)
        assert 'branch offset out of range' in result.stderr, result.stderr
        print('PASS image and fixup diagnostics')
    print('All Nosuz16 backend execution tests passed.')


if __name__ == '__main__':
    main()
