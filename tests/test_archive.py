"""Synthetic archive-boundary tests; no upstream software is executed."""
import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('extract_qpdf', Path(__file__).resolve().parents[1] / 'scripts/extract_qpdf.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ArchiveTests(unittest.TestCase):
    def archive(self, root, extra):
        path = root / 'input.zip'
        with zipfile.ZipFile(path, 'w') as z:
            regular = zipfile.ZipInfo('bin/qpdf'); regular.external_attr = (stat.S_IFREG | 0o755) << 16
            z.writestr(regular, b'synthetic executable bytes, never run')
            for name, mode, data in extra:
                info = zipfile.ZipInfo(name); info.external_attr = mode << 16
                z.writestr(info, data)
        return path

    def test_internal_library_link_chain_keeps_exact_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.archive(root, [('lib/libqpdf.so.30.4.2', stat.S_IFREG | 0o644, b'literal library'),
                                          ('lib/libqpdf.so.30', stat.S_IFLNK | 0o777, b'libqpdf.so.30.4.2'),
                                          ('lib/libqpdf.so', stat.S_IFLNK | 0o777, b'libqpdf.so.30')])
            records = module.extract_layout(archive, root / 'out')
            self.assertEqual((root / 'out/lib/libqpdf.so').read_bytes(), b'literal library')
            self.assertTrue((root / 'out/lib/libqpdf.so').is_symlink())
            self.assertEqual(len(records), 4)
            with self.assertRaises(ValueError):
                module.extract_layout(archive, root / 'out')

    def test_unsafe_archive_layouts_fail_before_writes(self):
        cases = [
            [('lib/a', stat.S_IFLNK | 0o777, b'/etc/passwd')],
            [('lib/a', stat.S_IFLNK | 0o777, b'../bin/qpdf')],
            [('lib/a', stat.S_IFLNK | 0o777, b'missing')],
            [('lib/a', stat.S_IFLNK | 0o777, b'b'), ('lib/b', stat.S_IFLNK | 0o777, b'a')],
            [('../escape', stat.S_IFREG | 0o644, b'x')],
            [('/lib/absolute', stat.S_IFREG | 0o644, b'x')],
            [('lib/nested/file', stat.S_IFREG | 0o644, b'x')],
            [('lib/a', stat.S_IFIFO | 0o644, b'')],
            [('bin/other', stat.S_IFREG | 0o755, b'x')],
            [('bin/qpdf', stat.S_IFREG | 0o755, b'duplicate')],
        ]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self.archive(root, case)
                with self.assertRaises(ValueError):
                    module.extract_layout(archive, root / 'out')
                self.assertFalse((root / 'out').exists())
