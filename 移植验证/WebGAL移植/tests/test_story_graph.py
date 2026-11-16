import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_story_graph import ROOT, trace
from mac_story_wiring import emit_choice, emit_transitions, read_translations
from 回放剧情状态 import read_scene_table, replay


class StoryGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = BASE / '数据'
        index = json.loads((data / '入口片段_扩展候选.json').read_text(encoding='utf-8'))
        checks = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))
        cls.graph = trace(index, checks, ROOT / '输出-保护边修复/MAC')
        cls.translations = read_translations(data / '选项v74地址核查.tsv')
        cls.wiring = emit_transitions(cls.graph, cls.translations)

    def test_main_candidate_graph_reaches_ending_and_checks_boundaries(self):
        self.assertEqual(self.graph['root'], 'MAC_000:0xC')
        self.assertIn('MAC_056:0x2D88', self.graph['reached_end_candidates'])
        self.assertNotIn('MAC_058:0x10514', self.graph['reached_end_candidates'])
        ids = {node['id'] for node in self.graph['nodes']}
        for node in self.graph['nodes']:
            for edge in node['edges']:
                if not edge.get('unresolved'):
                    self.assertIn(edge['target'], ids)

    def test_wiring_covers_verified_cross_script_and_future_choice(self):
        emitted = self.wiring['emitted']
        self.assertEqual(emitted['MAC_003:0x6790'], ['changeScene:mac_004_0x00000c.txt;'])
        self.assertIn('setVar:mac_6007=1 -next;', emitted['MAC_004:0xA38'])
        self.assertIn('setVar:mac_6000=1 -next;', emitted['MAC_004:0xA38'])
        self.assertIn('changeScene:mac_004_0x003244.txt;', emitted['MAC_004:0x2CBC'])

    def test_missing_translation_blocks_whole_choice_group(self):
        node = next(node for node in self.graph['nodes'] if node['id'] == 'MAC_004:0xA38')
        with self.assertRaisesRegex(ValueError, '第 0 项缺少'):
            emit_choice(node, {})

    def test_hidden_option_does_not_renumber_other_option(self):
        node = next(node for node in self.graph['nodes'] if node['id'] == 'MAC_003:0x24C4')
        lines = emit_choice(node, self.translations)
        self.assertTrue(lines[0].startswith('choose:(mac_6010!=0)->青梅竹马而已:option_0|'))
        self.assertIn('label:option_1 -next;', lines)
        self.assertIn('setVar:mac_6007=1 -next;', lines)

    def test_disc_scene_table_unblocks_last_progress_bit_in_diagnostic_replay(self):
        titles = json.loads((BASE / '数据/章节标题静态表.json').read_text(encoding='utf-8'))['records']
        table = read_scene_table(ROOT / '输出-保护边修复/SYSTEM/INIT.BIN')
        self.assertEqual(table, (bytes.fromhex('b4430000c043000000000000'),))
        blocked = replay(self.graph, titles, (0,), diagnostic=True)
        self.assertEqual((blocked['status'], blocked['site']), ('state_operation', 'MAC_056:0xC'))
        completed = replay(self.graph, titles, (0,), diagnostic=True, scene_table=table)
        self.assertEqual((completed['status'], completed['site']), ('end_candidate', 'MAC_056:0x2D88'))
        self.assertTrue(completed['omissions'])
