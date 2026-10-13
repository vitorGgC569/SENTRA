"""Small, deterministic ISO9660 seed media; no host directory is shared."""
from pathlib import Path
import struct

SECTOR = 2048


def _both(value, size=4):
    return value.to_bytes(size, 'little') + value.to_bytes(size, 'big')


def _record(name, sector, size, directory=False):
    data = bytearray(33 + len(name) + (len(name) % 2 == 0))
    data[0] = len(data)
    data[2:10] = _both(sector)
    data[10:18] = _both(size)
    data[18:25] = bytes((126, 1, 1, 0, 0, 0, 0))
    data[25] = 2 if directory else 0
    data[28:32] = _both(1, 2)
    data[32] = len(name)
    data[33:33 + len(name)] = name
    return data


def seed_iso(path, files):
    """Write a bounded single-directory ISO with fixed safe 8.3 filenames."""
    import re
    if not files or len(files) > 20:
        raise ValueError('bounded seed files required')
    entries, sector = [], 21
    for name, content in sorted(files.items()):
        if not re.fullmatch(r'[A-Z0-9_]{1,8}\.[A-Z0-9_]{1,3}', name) or not isinstance(content, bytes) or len(content) > 1048576:
            raise ValueError('invalid seed file')
        entries.append((name, content, sector))
        sector += (len(content) + SECTOR - 1) // SECTOR
    image = bytearray(sector * SECTOR)
    pvd = bytearray(SECTOR)
    pvd[:7] = b'\x01CD001\x01'
    pvd[8:40] = b'SENTRA'.ljust(32, b' ')
    pvd[40:72] = b'SENTRA_SEED'.ljust(32, b' ')
    pvd[80:88] = _both(sector)
    pvd[120:124] = _both(1, 2)
    pvd[124:128] = _both(1, 2)
    pvd[128:132] = _both(SECTOR, 2)
    pvd[132:140] = _both(10)
    struct.pack_into('<I', pvd, 140, 18)
    struct.pack_into('>I', pvd, 148, 19)
    root = _record(b'\0', 20, SECTOR, True)
    pvd[156:190] = root
    pvd[881] = 1
    image[16 * SECTOR:17 * SECTOR] = pvd
    image[17 * SECTOR:17 * SECTOR + 7] = b'\xffCD001\x01'
    image[18 * SECTOR:18 * SECTOR + 10] = b'\x01\0' + struct.pack('<IH', 20, 1) + b'\0\0'
    image[19 * SECTOR:19 * SECTOR + 10] = b'\x01\0' + struct.pack('>IH', 20, 1) + b'\0\0'
    directory = root + _record(b'\x01', 20, SECTOR, True)
    for name, content, start in entries:
        directory += _record((name + ';1').encode('ascii'), start, len(content))
        image[start * SECTOR:start * SECTOR + len(content)] = content
    if len(directory) > SECTOR:
        raise ValueError('seed directory limit')
    image[20 * SECTOR:20 * SECTOR + len(directory)] = directory
    with Path(path).open('xb') as output:
        output.write(image)
