import importlib.util
import json
from pathlib import Path
import struct
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent
sys.path.insert(0, str(BASE / '转换器'))
from mac_reader import load_table, read_entry_zero, read_linear_range


class EntryReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_table()
        cls.checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))

    def read_script(self, name):
        return (ROOT / '输出-保护边修复/MAC' / name).read_bytes()

    def test_normal_entry_does_not_treat_table_as_instruction(self):
        name = 'MAC_001.bin'
        entry, commands = read_entry_zero(self.read_script(name), self.checks[name]['boundary'], self.table)
        self.assertEqual(entry, 12)
        self.assertEqual(commands[0].offset, 12)
        self.assertNotIn(8, [c.offset for c in commands])
        self.assertIn(0x3878, [c.offset for c in commands])

    def test_debug_entry_points(self):
        for index, expected in ((63, 0x1718), (64, 0x240), (65, 0x124), (69, 0x88)):
            name = f'MAC_{index:03}.bin'
            entry, commands = read_entry_zero(self.read_script(name), self.checks[name]['boundary'], self.table)
            self.assertEqual(entry, expected)
            self.assertEqual(commands[0].offset, expected)

    def test_bad_entry_or_boundary_is_rejected(self):
        data = bytearray(self.read_script('MAC_001.bin'))
        boundary = self.checks['MAC_001.bin']['boundary']
        struct.pack_into('<I', data, 8, 8)
        with self.assertRaises(ValueError):
            read_entry_zero(data, boundary, self.table)
        with self.assertRaises(ValueError):
            read_entry_zero(data, len(data) + 1, self.table)

    def test_debug_subroutine_before_entry(self):
        data = self.read_script('MAC_069.bin')
        commands = read_linear_range(data, 0x0C, 0x88, self.table)
        self.assertEqual(commands[0].offset, 0x0C)
        self.assertEqual(commands[-1].opcode, 0x05)
        entry, following = read_entry_zero(data, self.checks['MAC_069.bin']['boundary'], self.table)
        calls = [c for c in following if c.opcode == 4 and struct.unpack_from('<I', c.data, 4)[0] == 0x0C]
        self.assertEqual(entry, 0x88)
        self.assertEqual(len(calls), 42)


if __name__ == '__main__':
    unittest.main()
