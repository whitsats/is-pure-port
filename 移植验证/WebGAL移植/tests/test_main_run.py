"""主线实跑报告：53 章、逐章标题/首句/变量、MAC_009 写回实证与离线结束指令。"""
import csv
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
RUN = BASE / '数据/主线实跑_全流程.json'
TABLE = BASE / '数据/主线停点表.tsv'


class MainRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(RUN.read_text(encoding='utf-8'))

    def test_runs_from_new_game_to_the_end_instruction(self):
        summary = self.report['summary']
        self.assertEqual(summary['chapters_reached'], 53)
        self.assertEqual(summary['last_chapter'], 'MAC_056')
        self.assertTrue(summary['end_instruction_reached'])
        self.assertFalse(summary['stalled'])
        self.assertEqual(self.report['end']['script'], 'MAC_056.bin')
        self.assertEqual(self.report['end']['offset'], '0x2D88')
        self.assertEqual(self.report['end']['raw_hex'], '01010000')

    def test_each_chapter_has_title_first_line_and_live_variables(self):
        missing = []
        for chapter in self.report['chapters']:
            if not chapter['title'] or not chapter['first_text']:
                missing.append(chapter['chapter'])
            state = chapter['state_readback'] or {}
            if 'mac_6007' not in state or 'mac_6000' not in state or 'mac_entry' not in state:
                missing.append(f"{chapter['chapter']}:vars")
        self.assertEqual(missing, [])
        titles_seen = [chapter['chapter'] for chapter in self.report['chapters']
                       if chapter['title_seen_in_runtime']]
        self.assertGreaterEqual(len(titles_seen), 45, titles_seen)

    def test_variables_are_read_back_from_the_live_module(self):
        mac_010 = next(chapter for chapter in self.report['chapters'] if chapter['chapter'] == 'MAC_010')
        self.assertEqual(mac_010['state_readback']['mac_6007'], mac_010['state_readback']['mac_6000'])
        checks = self.report.get('state_checks') or []
        self.assertTrue(checks, '缺少 MAC_009 选项写回核对')
        for check in checks:
            self.assertTrue(check['pass'], check)
        self.assertGreater(len(self.report['choices']), 30)

    def test_stop_table_classifies_the_end_instruction(self):
        self.assertTrue(TABLE.is_file(), TABLE)
        with TABLE.open(encoding='utf-8') as handle:
            rows = list(csv.DictReader(handle, delimiter='\t'))
        ends = [row for row in rows if row['类别'].startswith('end')]
        self.assertTrue(ends)
        for row in ends:
            self.assertEqual(row['剧本'], 'MAC_056.bin')
            self.assertEqual(row['偏移'], '0x2D88')
            self.assertEqual(row['原始字节'], '01010000')
            self.assertIn('跑主线到终点.cjs', row['复现命令'])
        self.assertFalse([row for row in rows if row['类别'].startswith('stall')])


if __name__ == '__main__':
    unittest.main()
