import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_reader import ROOT, load_table
from 可达候选 import explore


class ReachableTests(unittest.TestCase):
    def test_debug_mixed_code_and_data(self):
        data = (ROOT / '输出-保护边修复/MAC/MAC_068.bin').read_bytes()
        result = explore(data, 12, 9420, load_table())
        self.assertEqual(len(result['instructions']), 69)
        self.assertEqual(result['issues'], [])
        self.assertEqual(len(result['stops']), 2)
        self.assertNotIn(0x1C0C, {c['offset'] for c in result['instructions']})

    def test_out_of_range_entry_is_reported(self):
        data = (ROOT / '输出-保护边修复/MAC/MAC_068.bin').read_bytes()
        result = explore(data, 9420, 9420, load_table())
        self.assertEqual(result['instructions'], [])
        self.assertTrue(result['issues'])


if __name__ == '__main__':
    unittest.main()
