import csv
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(BASE.parent))
import MAC_批量选项分支 as original
from mac_choice import plan_choice
from mac_reader import ROOT, load_table, read_entry_zero
from mac_runtime_scene import compile_range, load_commands
from mac_state import State
from 验证新游戏首选项 import DATA, MAC

SCRIPT = 'MAC_003.bin'
OFFSET = 0x5A44
TARGETS = (0x5A90, 0x5EB4, 0x626C)


def load():
    data = (MAC / SCRIPT).read_bytes()
    info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))[SCRIPT]
    table = load_table()
    _, commands = read_entry_zero(data, info['boundary'], table)
    return data, info, table, {c.offset for c in commands}


class FifthChoiceTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.info, cls.table, cls.starts = load()
        cls.rows = original.inspect(cls.data, OFFSET, cls.info['text_start'], cls.starts)

    def test_layout_matches_the_earlier_choices(self):
        raw = self.data[OFFSET:OFFSET + 20]
        self.assertEqual(raw[0], 0x72)
        self.assertEqual(raw[1], 3)
        self.assertEqual(raw[2:4], bytes.fromhex('0760'))
        self.assertEqual(raw[12:20], bytes.fromhex('09 00 00 60 07 60 00 00'))
        pointer = int.from_bytes(raw[4:8], 'little')
        self.assertEqual(pointer, 0x7714)
        self.assertLess(pointer + 12 * self.rows.__len__(), self.info['text_start'])

    def test_targets_are_command_boundaries(self):
        self.assertEqual([row[2] for row in self.rows], list(TARGETS))
        for target in TARGETS:
            self.assertIn(target, self.starts)

    def test_labels_come_from_the_disc_text(self):
        self.assertEqual([row[1] for row in self.rows],
                         ['いいかげんにしろ！', '冗談だろ？', '…………'])

    def test_translations_are_unique_and_match_the_disc(self):
        with (DATA / '选项v74地址核查.tsv').open(encoding='utf-8-sig', newline='') as file:
            rows = {int(row['表内序号']): row for row in csv.DictReader(file, delimiter='\t')
                    if row['脚本'] == SCRIPT and int(row['选项指令偏移'], 16) == OFFSET}
        self.assertEqual(len(rows), 3)
        for index, label, *_ in self.rows:
            self.assertEqual(rows[index]['匹配状态'], '唯一匹配')
            self.assertEqual(rows[index]['日文原文'], label)

    def test_all_options_are_visible_without_state(self):
        plan = plan_choice(self.data, self.info['boundary'], self.info['text_start'], OFFSET,
                           self.table, State())
        self.assertEqual(plan['visible_indices'], [0, 1, 2])
        self.assertEqual([option['condition']['raw'] for option in plan['options']],
                         ['0x0001'] * 3)


class FifthBranchScene(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = compile_range(SCRIPT, 0x5A90, extra_labels=TARGETS)

    def test_three_entry_labels_exist(self):
        self.assertTrue(set(TARGETS) <= set(self.result.labels))

    def test_runs_from_branch_entry_to_cross_script_boundary(self):
        self.assertGreater(len(self.result.lines), 200)
        self.assertEqual((self.result.stop.offset, self.result.stop.name, self.result.stop.category),
                         (0x6790, 'ext_goto', 'cross_script'))
        self.assertFalse(self.result.unresolved_targets)

    def test_no_choice_or_effect_is_silently_emitted(self):
        text = '\n'.join(self.result.lines)
        self.assertNotIn('choose:', text)
        self.assertNotIn('effect_start', text)

    def test_extra_label_must_be_a_boundary(self):
        with self.assertRaises(ValueError):
            compile_range(SCRIPT, 0x5A90, extra_labels=(0x5A91,))


class FifthSample(unittest.TestCase):
    """生成物存在时校验场景链；不存在时跳过，避免测试依赖可再生成的样片。"""

    sample = BASE / '历史样片/新游戏动态第五选项/public/game/scene'

    def setUp(self):
        if not self.sample.is_dir():
            self.skipTest('第五选项样片未生成')

    def test_chain_from_fourth_to_fifth_to_branches(self):
        fourth = (self.sample / 'mac003_to_fourth.txt').read_text(encoding='utf-8')
        self.assertTrue(fourth.rstrip().endswith('changeScene:mac003_fifth.txt;'))
        fifth = (self.sample / 'mac003_fifth.txt').read_text(encoding='utf-8').splitlines()
        choose = [line for line in fifth if line.startswith('choose:')]
        self.assertEqual(len(choose), 1)
        self.assertEqual(choose[0].count('|') + 1, 3)
        self.assertIn('changeScene:mac003_fifth_branches.txt;', fifth)
        branches = (self.sample / 'mac003_fifth_branches.txt').read_text(encoding='utf-8').splitlines()
        for index, target in enumerate(TARGETS):
            self.assertIn(f'jumpLabel:mac_{target:x} -when=mac_entry=={index};', branches)
            self.assertIn(f'label:mac_{target:x} -next;', branches)

    def test_state_words_are_initialised(self):
        start = (self.sample / 'start.txt').read_text(encoding='utf-8')
        for word in ('6000', '6007', '6010', '6014', '601a', 'a012', 'a013', 'mac_entry'):
            self.assertIn(word, start)


if __name__ == '__main__':
    unittest.main()
