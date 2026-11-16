import csv
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(BASE.parent))
from mac_choice import plan_choice, read_options
from mac_reader import ROOT, load_table, read_entry_zero
from mac_runtime_scene import compile_range, scan_blockers
from mac_state import State
from 验证新游戏首选项 import DATA, MAC

BRANCH_START = 0x5A90
BRANCH_TARGETS = (0x5A90, 0x5EB4, 0x626C)
MAC004_START = 0x0C
CHOICE = 0xA38
BOUNDARY = (0xA38, 'sel_disp4', 'choice')
BRANCH_ENTRIES = (0xA6C, 0xBF0)
BRANCH_LIMIT = (0x1AA8, 'effect_start', 'effect')


def scene_name(script, entry):
    return f'{Path(script).stem.lower()}_0x{entry:06x}.txt'


class ExtGotoContinuation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = compile_range('MAC_003.bin', BRANCH_START, extra_labels=BRANCH_TARGETS,
                                   ext_scene=scene_name)

    def test_branch_scene_ends_with_change_scene(self):
        self.assertEqual(self.result.lines[-1], 'changeScene:mac_004_0x00000c.txt;')

    def test_jump_target_is_read_from_the_disc(self):
        self.assertEqual(len(self.result.ext_jumps), 1)
        jump = self.result.ext_jumps[0]
        self.assertEqual((jump['group'], jump['index']), (0, 4))
        self.assertEqual(jump['target_script'], 'MAC_004.bin')
        self.assertEqual(jump['target_entry'], MAC004_START)
        self.assertEqual(jump['target_header'], '09 11 00 60 08 00 00 00')
        self.assertTrue(jump['webgal']['mapped'])

    def test_stop_reports_the_continuation(self):
        self.assertEqual((self.result.stop.offset, self.result.stop.name), (0x6790, 'ext_goto'))
        self.assertEqual(self.result.stop.category, 'cross_script')
        self.assertIn('changeScene:mac_004_0x00000c.txt', self.result.stop.reason)

    def test_without_ext_scene_the_jump_stays_a_blocker(self):
        plain = compile_range('MAC_003.bin', BRANCH_START, extra_labels=BRANCH_TARGETS)
        self.assertEqual(plain.stop.category, 'cross_script')
        self.assertNotIn('changeScene:mac_004_0x00000c.txt;', plain.lines)


class Mac004Opening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = compile_range('MAC_004.bin', MAC004_START)

    def test_runs_to_the_first_choice(self):
        self.assertGreater(len(self.result.lines), 100)
        stop = self.result.stop
        self.assertEqual((stop.offset, stop.name, stop.category), BOUNDARY)

    def test_chapter_title_comes_from_the_static_table(self):
        titles = [line for line in self.result.lines if line.startswith('intro:')]
        self.assertEqual(titles, ['intro:新生欢迎晚会;'])

    def test_progress_bit_is_recorded_not_silently_dropped(self):
        bits = [entry for entry in self.result.ignored if entry['category'] == 'progress_bit']
        self.assertEqual([(entry['offset'], entry['operand']) for entry in bits], [(0x5C, 4)])
        self.assertEqual(bits[0]['previous'], 0)

    def test_state_words_come_from_the_range(self):
        # 0x0C 起的 if 读 mac_a013；它就是 MAC_004 开头叙述段的门控。
        self.assertIn('mac_a013', '\n'.join(self.result.lines))

    def test_title_without_the_leading_0x17_is_blocked(self):
        bare = compile_range('MAC_004.bin', 0x68)
        self.assertEqual(bare.stop.category, 'title')
        self.assertIn('不是本区间内 0x17 写入的', bare.stop.reason)


class Mac004Scan(unittest.TestCase):
    def test_remaining_blockers_are_categorised_with_counts(self):
        scan = scan_blockers('MAC_004.bin', MAC004_START)
        counts = {entry['category']: entry['count'] for entry in scan['blockers']}
        self.assertEqual(counts, {'choice': 1, 'effect': 17, 'cross_script': 2})
        self.assertEqual(scan['blocker_total'], 20)
        # 0xA38 是本轮接线的选项：单列在 wired 里，不再算阻塞。
        self.assertEqual([w['offset'] for w in scan['wired']], ['0xA38'])
        self.assertEqual(scan['wired'][0]['category'], 'choice')
        for supported in ('title', 'reg_calc'):
            self.assertNotIn(supported, counts)


class Mac004Choice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (MAC / 'MAC_004.bin').read_bytes()
        cls.info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_004.bin']
        cls.table = load_table()
        _, cls.commands = read_entry_zero(cls.data, cls.info['boundary'], cls.table)
        cls.choice = read_options(cls.data, cls.info, cls.table, cls.commands, CHOICE,
                                  'MAC_004.bin', DATA / '选项v74地址核查.tsv',
                                  bytes.fromhex('72020760'))

    def test_layout_matches_the_other_choices(self):
        raw = self.data[CHOICE:CHOICE + 20]
        self.assertEqual(raw[:4], bytes.fromhex('72 02 07 60'))
        self.assertEqual(raw[12:20], bytes.fromhex('09 00 00 60 07 60 00 00'))
        self.assertEqual(self.choice['table_pointer'], 0x3F08)
        self.assertLess(self.choice['table_pointer'] + 12 * len(self.choice['options']),
                        self.info['text_start'])

    def test_targets_and_texts_come_from_the_disc(self):
        options = self.choice['options']
        self.assertEqual([option['target'] for option in options], list(BRANCH_ENTRIES))
        self.assertEqual([option['label_original'] for option in options],
                         ['そのうち来るだろう', 'いつきを捜す'])
        self.assertEqual([option['text'] for option in options], ['她过会就会来吧', '去找季子'])

    def test_both_options_are_visible_without_state(self):
        plan = plan_choice(self.data, self.info['boundary'], self.info['text_start'], CHOICE,
                           self.table, State())
        self.assertEqual(plan['visible_indices'], [0, 1])
        self.assertEqual([option['condition_raw'] for option in self.choice['options']], [1, 1])


class Mac004Branches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = [compile_range('MAC_004.bin', entry) for entry in BRANCH_ENTRIES]

    def test_each_branch_runs_to_the_effect_boundary(self):
        for result in self.results:
            self.assertGreater(len(result.lines), 200)
            self.assertEqual((result.stop.offset, result.stop.name, result.stop.category), BRANCH_LIMIT)
            self.assertFalse(result.unresolved_targets)

    def test_branches_start_at_their_own_entry(self):
        firsts = ['一贵「没关系的吧。她说了会来」', '……已经两点了。她到底在干吗啊？']
        for result, first in zip(self.results, firsts):
            self.assertTrue(result.lines[0].startswith(first), result.lines[0])

    def test_branch_entries_are_command_boundaries(self):
        commands = json.loads((DATA / '入口片段.json').read_text(encoding='utf-8'))['scripts']
        offsets = {command['offset'] for source in commands if source['file'] == 'MAC_004.bin'
                   for command in source['commands']}
        self.assertTrue(set(BRANCH_ENTRIES) <= offsets)


class WiringRegistry(unittest.TestCase):
    def test_entries_match_real_commands(self):
        from mac_runtime_scene import load_commands
        from mac_wiring import WIRED
        for (script, offset), info in WIRED.items():
            names = {command['offset']: command['name'] for command in load_commands(script)}
            self.assertIn(offset, names, f'{script} 缺少 {offset:#x}')
            expected = 'sel_disp4' if info['kind'] == 'choice' else 'ext_goto'
            self.assertEqual(names[offset], expected)
            self.assertTrue((BASE / info['scene']).is_file(), info['scene'])

    def test_scan_puts_wired_offsets_aside(self):
        scan = scan_blockers('MAC_004.bin', MAC004_START)
        self.assertNotIn('0xA38', [offset for entry in scan['blockers']
                                   for offset in entry['offsets']])
        self.assertIn('0xA38', [entry['offset'] for entry in scan['wired']])
        self.assertEqual(scan['blocker_total'] + scan['wired_total'], 21)


class BlockerReport(unittest.TestCase):
    """`数据/` 下的分类报告必须等于工具当前的输出，不允许手工维护。"""

    def test_report_matches_fresh_scan(self):
        report = json.loads((DATA / '动态场景编译报告_MAC004_0x0C.json')
                            .read_text(encoding='utf-8'))['scan']
        fresh = scan_blockers('MAC_004.bin', MAC004_START)
        self.assertEqual(report['blocker_total'], fresh['blocker_total'])
        self.assertEqual([(entry['category'], entry['count']) for entry in report['blockers']],
                         [(entry['category'], entry['count']) for entry in fresh['blockers']])
        self.assertEqual([entry['offsets'] for entry in report['blockers']],
                         [entry['offsets'] for entry in fresh['blockers']])
        self.assertEqual([entry['offset'] for entry in report['wired']],
                         [entry['offset'] for entry in fresh['wired']])

    def test_sample_report_matches_fresh_scan(self):
        report = json.loads((BASE / '历史样片/新游戏动态MAC004/生成报告.json')
                            .read_text(encoding='utf-8'))['mac004_scan']
        fresh = scan_blockers('MAC_004.bin', MAC004_START)
        self.assertEqual(report['blocker_total'], fresh['blocker_total'])
        self.assertEqual([entry['count'] for entry in report['blockers']],
                         [entry['count'] for entry in fresh['blockers']])


class Mac004Sample(unittest.TestCase):
    sample = BASE / '历史样片/新游戏动态MAC004/public/game/scene'

    def setUp(self):
        if not self.sample.is_dir():
            self.skipTest('MAC_004 接续样片未生成')

    def test_chain_from_branch_to_mac004_choice_to_branches(self):
        branches = (self.sample / 'mac003_fifth_branches.txt').read_text(encoding='utf-8').splitlines()
        self.assertEqual(branches[-1], 'changeScene:mac_004_0x00000c.txt;')
        for index, target in enumerate(BRANCH_TARGETS):
            self.assertIn(f'jumpLabel:mac_{target:x} -when=mac_entry=={index};', branches)
        opening = (self.sample / 'mac_004_0x00000c.txt').read_text(encoding='utf-8').splitlines()
        self.assertIn('choose:她过会就会来吧:mac004_choice_0|去找季子:mac004_choice_1;', opening)
        for index, entry in enumerate(BRANCH_ENTRIES):
            self.assertIn(f'label:mac004_choice_{index} -next;', opening)
            self.assertIn(f'setVar:mac_6007={index} -next;', opening)
            self.assertIn(f'changeScene:mac_004_0x{entry:06x}.txt;', opening)
        for entry in BRANCH_ENTRIES:
            branch = (self.sample / f'mac_004_0x{entry:06x}.txt').read_text(encoding='utf-8').splitlines()
            self.assertTrue(branch[-2].startswith('本版边界：MAC_004.bin 0x1AA8'))
            self.assertEqual(branch[-1], 'end;')

    def test_new_state_words_are_initialised(self):
        start = (self.sample / 'start.txt').read_text(encoding='utf-8')
        for word in ('a011', 'a013', 'a014', '6010', 'a012'):
            self.assertIn(f'setVar:mac_{word}=0 -next;', start)


if __name__ == '__main__':
    unittest.main()
