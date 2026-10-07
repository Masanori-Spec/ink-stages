"""Extract only the checksum-pinned official qpdf bin/lib release layout."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import stat
import sys
import zipfile

SIZE = 4040257
SHA256 = 'db367d897829f22c4198ce1094143c9d467bd6ee7dfabc44ba6f02056b24f8b1'
NAME = re.compile(r'[A-Za-z0-9_.+\-]+\Z')


def extract_layout(archive, destination):
    """Validate the whole archive before writing; links may only alias local libs."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('qpdf extraction destination must be fresh')
    with zipfile.ZipFile(archive) as z:
        infos = z.infolist()
        if len(infos) > 2048 or sum(i.file_size for i in infos) > 128 * 1024 * 1024:
            raise ValueError('qpdf archive bounds exceeded')
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip() is not None:
            raise ValueError('Duplicate or corrupt qpdf archive members')
        members, links = {}, {}
        for i in infos:
            p = PurePosixPath(i.filename)
            mode = stat.S_IFMT(i.external_attr >> 16)
            if i.is_dir() and i.filename in {'bin/', 'lib/'}:
                continue
            if len(p.parts) != 2 or p.parts[0] not in {'bin', 'lib'} or not NAME.fullmatch(p.name) or p.name in {'.', '..'}:
                raise ValueError('Unsupported qpdf member path')
            if i.filename != p.as_posix() or i.flag_bits & 1:
                raise ValueError('Ambiguous or encrypted qpdf member')
            if mode not in {0, stat.S_IFREG, stat.S_IFLNK}:
                raise ValueError('Unsupported qpdf member type')
            if p.parts[0] == 'bin' and (p.name not in {'qpdf', 'fix-qdf', 'zlib-flate'} or mode == stat.S_IFLNK):
                raise ValueError('Unsupported qpdf executable')
            members[i.filename] = i
            if mode == stat.S_IFLNK:
                if i.file_size > 256:
                    raise ValueError('Oversized qpdf link')
                target = z.read(i).decode('ascii')
                if not NAME.fullmatch(target) or target in {'.', '..'}:
                    raise ValueError('qpdf library link must target a basename')
                links[i.filename] = target
        if 'bin/qpdf' not in members:
            raise ValueError('qpdf executable missing')
        for name in links:
            current, seen = name, set()
            while current in links:
                if current in seen:
                    raise ValueError('Cyclic qpdf library link')
                seen.add(current)
                current = 'lib/' + links[current]
            if current not in members or not current.startswith('lib/'):
                raise ValueError('qpdf link target is missing or outside lib')
        destination.mkdir()
        inventory = []
        for name, info in members.items():
            target = destination / name
            target.parent.mkdir(exist_ok=True)
            if name in links:
                inventory.append({'name': name, 'type': 'symlink', 'target': links[name]})
                continue
            data = z.read(info)
            with target.open('xb') as f:
                f.write(data)
            target.chmod(0o755 if name.startswith('bin/') else 0o644)
            inventory.append({'name': name, 'type': 'file', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        for name, target in links.items():
            os.symlink(target, destination / name)
        return inventory


if __name__ == '__main__':
    archive, destination, report = map(Path, sys.argv[1:])
    if archive.stat().st_size != SIZE or hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Official qpdf release size/digest mismatch')
    inventory = extract_layout(archive, destination)
    with report.open('x') as f:
        json.dump(inventory, f, indent=2)
        f.write('\n')
