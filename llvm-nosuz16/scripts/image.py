#!/usr/bin/env python3
"""Resolve private Nosuz16 MC objects into a flat byte-addressed HEX/BIN image."""
import argparse
from dataclasses import dataclass
from pathlib import Path
import struct


@dataclass
class Object:
    path: Path
    sections: list
    symbols: dict


def load_object(path):
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x01\x01':
        raise ValueError(f'{path}: expected little-endian ELF32 MC transport object')
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    if header[1:3] != (1, 0):
        raise ValueError(f'{path}: expected private Nosuz16 ET_REL/EM_NONE object')
    if header[7] != 0x205:
        raise ValueError(f'{path}: expected Nosuz16 v2.5 object; rebuild older objects')
    offset, stride, count = header[6], header[11], header[12]
    if stride != 40 or offset + count * stride > len(data):
        raise ValueError(f'{path}: invalid section table')
    sections = []
    for index in range(count):
        fields = struct.unpack_from('<10I', data, offset + index * stride)
        name, kind, flags, address, start, size, link, info, align, entsize = fields
        if flags & 2 and size > 0x10000:
            raise ValueError(f'{path}: allocated section exceeds CPU address space')
        if kind != 8 and start + size > len(data):
            raise ValueError(f'{path}: truncated section')
        payload = bytearray(size) if kind == 8 else bytearray(data[start:start + size])
        sections.append(dict(kind=kind, flags=flags, data=payload, size=size,
                             link=link, info=info, align=align, entsize=entsize))
    symbol_tables = {}
    for index, section in enumerate(sections):
        if section['kind'] != 2:
            continue
        if section['entsize'] != 16 or section['size'] % 16:
            raise ValueError(f'{path}: invalid symbol table')
        strings = sections[section['link']]['data']
        entries = []
        for position in range(0, section['size'], 16):
            name, value, size, info, other, shndx = struct.unpack_from('<IIIBBH', section['data'], position)
            end = strings.find(0, name)
            if end < 0:
                raise ValueError(f'{path}: invalid symbol name')
            entries.append(dict(name=strings[name:end].decode(), value=value,
                                binding=info >> 4, section=shndx))
        symbol_tables[index] = entries
    return Object(path, sections, symbol_tables)


def link(paths, origin):
    objects = [load_object(path) for path in paths]
    segments = [(obj, index, section) for obj in objects
                for index, section in enumerate(obj.sections) if section['flags'] & 2 and section['size']]
    # All executable sections precede data. Input order determines startup order.
    segments.sort(key=lambda item: not bool(item[2]['flags'] & 4))
    base = origin
    image = bytearray()
    for obj, index, section in segments:
        if section['kind'] not in (1, 8):
            raise ValueError(f'{obj.path}: unsupported allocated section')
        alignment = max(1, section['align'])
        if alignment & (alignment - 1) or (section['flags'] & 4 and section['size'] % 2):
            raise ValueError(f'{obj.path}: sections must contain aligned words')
        padding = (-base) % alignment
        image.extend(b'\x00' * padding)
        base += padding
        section['base'] = base
        image.extend(section['data'])
        base += section['size']
    if not image:
        raise ValueError('image contains no allocated bytes')
    # The reference startup uses a descending stack below FF00; no image in I/O.
    if base > 0xff00:
        raise ValueError('image reaches the reference I/O/stack boundary FF00')
    definitions = {}
    def symbol_address(obj, symbol):
        index = symbol['section']
        if index == 0xfff1:
            return symbol['value']
        if index == 0 or index >= len(obj.sections) or 'base' not in obj.sections[index]:
            raise ValueError(f"{obj.path}: unresolved or nonallocated symbol {symbol['name']}")
        return obj.sections[index]['base'] + symbol['value']
    for obj in objects:
        for entries in obj.symbols.values():
            for symbol in entries:
                if symbol['binding'] and symbol['section']:
                    name = symbol['name']
                    if name in definitions and symbol['binding'] != 2 and definitions[name][1]['binding'] != 2:
                        raise ValueError(f'duplicate symbol: {name}')
                    if name not in definitions or symbol['binding'] != 2:
                        definitions[name] = obj, symbol
    for obj in objects:
        for relocations in obj.sections:
            if relocations['kind'] != 4:
                continue
            target = obj.sections[relocations['info']]
            if not target['size']:
                continue
            if 'base' not in target:
                raise ValueError(f'{obj.path}: relocation against a nonallocated section')
            if relocations['entsize'] != 12 or relocations['size'] % 12:
                raise ValueError(f'{obj.path}: invalid relocation table')
            entries = obj.symbols[relocations['link']]
            for position in range(0, relocations['size'], 12):
                offset, info, addend = struct.unpack_from('<IIi', relocations['data'], position)
                symbol = entries[info >> 8]
                kind = info & 255
                defining_obj = obj
                if symbol['section'] == 0:
                    if symbol['name'] not in definitions:
                        raise ValueError(f"undefined symbol: {symbol['name']}")
                    defining_obj, symbol = definitions[symbol['name']]
                value = symbol_address(defining_obj, symbol) + addend
                if kind in (1, 2, 6) and value % 2:
                    raise ValueError('branch target is not instruction aligned')
                start = target['base'] - origin + offset
                required = 66 if kind in (3, 6) else 2
                if offset + required > target['size']:
                    raise ValueError('relocation exceeds its section')
                word = struct.unpack_from('<H', image, start)[0]
                if kind in (1, 2):
                    bits = 6 if kind == 1 else 9
                    delta = (value - (target['base'] + offset) - 2) & 65535
                    displacement = (delta if delta < 32768 else delta - 65536) // 2
                    if not -(1 << (bits - 1)) <= displacement < (1 << (bits - 1)):
                        raise ValueError('branch relocation out of range')
                    struct.pack_into('<H', image, start, (word & ~((1 << bits) - 1)) | (displacement & ((1 << bits) - 1)))
                elif kind in (3, 6):
                    if not 0 <= value <= 0xffff:
                        raise ValueError('byte address exceeds 16 bits')
                    for bit in range(16):
                        at = start + (2 + bit * 2) * 2
                        instruction = struct.unpack_from('<H', image, at)[0]
                        struct.pack_into('<H', image, at, (instruction & ~1) | ((value >> (15 - bit)) & 1))
                elif kind == 4:
                    if not 0 <= value <= 0xffff:
                        raise ValueError('byte pointer exceeds 16 bits')
                    struct.pack_into('<H', image, start, value)
                else:
                    raise ValueError(f'unsupported private relocation {kind}')
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('objects', nargs='+', type=Path)
    parser.add_argument('-o', '--output', required=True, type=Path)
    parser.add_argument('--origin', type=lambda value: int(value, 0), default=0)
    parser.add_argument('--format', choices=['hex', 'bin'])
    args = parser.parse_args()
    try:
        if not 0 <= args.origin < 0xff00 or args.origin & 1:
            raise ValueError('origin must be an even RAM byte address below FF00')
        image = link(args.objects, args.origin)
        kind = args.format or ('bin' if args.output.suffix == '.bin' else 'hex')
        if kind == 'bin':
            args.output.write_bytes(image)
        else:
            if len(image) % 2:
                image.append(0)  # HEX word transport explicitly pads the final byte.
            words = struct.unpack(f'<{len(image) // 2}H', image)
            args.output.write_text(''.join(f'{word:04X}\n' for word in words))
    except (ValueError, IndexError, KeyError, UnicodeError, struct.error, OSError) as error:
        parser.exit(1, f'nosuz16-image: {error}\n')


if __name__ == '__main__':
    main()
