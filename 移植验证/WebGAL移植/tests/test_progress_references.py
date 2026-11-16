import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 扫描章节进度引用 import context_overlap, scan


class ProgressReferenceTests(unittest.TestCase):
    def test_context_word_and_bit_aliases(self):
        self.assertEqual(context_overlap(0x6110)['overlap'], ['章节索引'])
        self.assertEqual(context_overlap(0x6148)['overlap'], ['该章节旧进度'])
        self.assertEqual(context_overlap(0xA480)['overlap'], ['该章节旧进度'])
        self.assertIsNone(context_overlap(0x0001))
        self.assertIsNone(context_overlap(0x6007))

    def test_candidate_scan_keeps_known_scope_and_sites(self):
        data = BASE / '数据'
        ir = json.loads((data / '入口片段_扩展候选.json').read_text(encoding='utf-8'))
        titles = json.loads((data / '章节标题静态表.json').read_text(encoding='utf-8'))['records']
        report = scan(ir, titles)
        self.assertEqual(report['scripts'], 73)
        self.assertEqual(report['counts']['reg17'], 84)
        self.assertEqual(report['counts']['distinct_indices'], 57)
        self.assertEqual(report['counts']['context_operand_mentions'], 0)
        self.assertEqual(report['counts']['unsupported_if_or_calc'], 16)
        self.assertIn('MAC_068', str(report['skipped']))
        sites = {(x['script'], x['offset']) for x in report['indices'][0]['write_sites']}
        self.assertIn(('MAC_000.bin', 0x78), sites)
        self.assertFalse(report['out_of_range_writes'])


if __name__ == '__main__':
    unittest.main()
