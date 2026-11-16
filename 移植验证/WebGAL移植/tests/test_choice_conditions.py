import json
from pathlib import Path
import struct
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_choice import plan_choice
from mac_reader import ROOT, load_table
from mac_state import State, UnsupportedCommand


class ChoiceConditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / '输出-保护边修复/MAC/MAC_001.bin').read_bytes()
        cls.info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_001.bin']
        cls.table = load_table()

    def plan(self, data, state):
        return plan_choice(data, self.info['boundary'], self.info['text_start'], 0x3878, self.table, state)

    def test_condition_filter_preserves_original_index(self):
        data = bytearray(self.source)
        records = struct.unpack_from('<I', data, 0x387C)[0]
        struct.pack_into('<H', data, records + 12 + 8, 0xA010)
        state = State()
        hidden = self.plan(data, state)
        self.assertEqual(hidden['visible_indices'], [0, 2])
        self.assertEqual(hidden['options'][2]['target'], 0x40B8)
        state.write(0xA010, 1)
        self.assertEqual(self.plan(data, state)['visible_indices'], [0, 1, 2])

    def test_no_visible_options_reports_original_count(self):
        data = bytearray(self.source)
        records = struct.unpack_from('<I', data, 0x387C)[0]
        for i in range(3):
            struct.pack_into('<H', data, records + i * 12 + 8, 0)
        result = self.plan(data, State())
        self.assertEqual(result['visible_indices'], [])
        self.assertEqual(result['no_visible_result'], 3)

    def test_unrecognised_branch_format_is_rejected(self):
        data = bytearray(self.source)
        data[0x3884] = 0xFF
        with self.assertRaises((UnsupportedCommand, ValueError)):
            self.plan(data, State())


if __name__ == '__main__':
    unittest.main()
