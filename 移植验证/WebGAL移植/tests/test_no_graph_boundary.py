import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_reader import ROOT, load_table
from 检查无画面边界 import inspect


class BoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_table()
        cls.info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))

    def test_startup_candidate_and_targets(self):
        name = 'MAC_061.bin'
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        result = inspect(data, self.info[name]['text_start'], self.table)
        self.assertEqual((result['entry'], result['candidate_end']), (0xC4, 0x108))
        self.assertEqual(len(result['targets']), 7)
        self.assertTrue(all(t['in_fragment'] for t in result['targets']))

    def test_mixed_debug_data_not_treated_as_end_marker(self):
        name = 'MAC_068.bin'
        data = (ROOT / '输出-保护边修复/MAC' / name).read_bytes()
        with self.assertRaisesRegex(ValueError, '未知命令或数据'):
            inspect(data, self.info[name]['text_start'], self.table)


if __name__ == '__main__':
    unittest.main()
