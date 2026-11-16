import csv
import json
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))

from mac_new_game import NewGameRuntime
from emit_webgal import convert_chain, normalize_mapping_row
from mac_state import UnsupportedCommand

TITLES = json.loads((BASE / '数据/章节标题静态表.json').read_text(encoding='utf-8'))['records']
IR = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
MAC_DIR = BASE.parent / '输出-保护边修复/MAC'


class NewGameRuntimeTests(unittest.TestCase):
    def test_initial_profile_is_zero_and_has_57_story_slots(self):
        runtime = NewGameRuntime(TITLES)
        self.assertEqual(runtime.story_count, 57)
        self.assertEqual(runtime.report()['visited_set_count'], 0)
        self.assertEqual(runtime.state.memory_bytes, {})

    def test_reg17_first_operand_writes_index_old_bit_and_sets_bit(self):
        runtime = NewGameRuntime(TITLES)
        result = runtime.apply_reg17(bytes.fromhex('0917000000000000'))
        self.assertEqual(result['operand'], 0)
        self.assertEqual(result['previous_bit'], 0)
        self.assertFalse(result['all_set'])
        self.assertEqual(runtime.state.read_context_u16(0x440), 0)
        self.assertEqual(runtime.state.read_context_u32(0x4B0), 0)
        self.assertEqual(runtime.bit(0), 1)
        self.assertEqual(result['bits_after'], 1)

    def test_reg17_second_operand_keeps_old_bit_zero(self):
        runtime = NewGameRuntime(TITLES)
        runtime.apply_reg17(bytes.fromhex('0917000000000000'))
        result = runtime.apply_reg17(bytes.fromhex('0917010000000000'))
        self.assertEqual(result['operand'], 1)
        self.assertEqual(result['previous_bit'], 0)
        self.assertEqual(runtime.state.read_context_u16(0x440), 1)
        self.assertEqual(runtime.state.read_context_u32(0x4B0), 0)
        self.assertEqual(runtime.bit(1), 1)
        self.assertFalse(result['all_set'])

    def test_all_set_without_scene_table_is_rejected(self):
        runtime = NewGameRuntime(TITLES)
        for index in range(56):
            runtime.set_bit(index)
        with self.assertRaisesRegex(UnsupportedCommand, '场景表'):
            runtime.apply_reg17(bytes.fromhex('0917380000000000'))  # 56
        self.assertEqual(runtime.state.memory_bytes, {})

    def test_vib_set_writes_exact_state_bytes(self):
        runtime = NewGameRuntime(TITLES)
        result = runtime.apply_vib_set(bytes.fromhex('5710060405010000'))
        self.assertEqual(result['bytes_1_to_5'], [0x10, 0x06, 0x04, 0x05, 0x01])
        self.assertEqual([runtime.state.read_context_u16(0x299 + i) & 0xFF for i in range(5)],
                         [0x10, 0x06, 0x04, 0x05, 0x01])
        for offset in (0x28C, 0x290, 0x294):
            self.assertEqual(runtime.state.read_context_u32(offset), 0)
        self.assertEqual(result['webgal']['mapped'], False)
        self.assertIn('不跳过', result['webgal']['reason'])

    def test_quick_save_records_checkpoint_without_changing_state(self):
        runtime = NewGameRuntime(TITLES)
        before = dict(runtime.state.memory_bytes)
        result = runtime.apply_quick_save(bytes.fromhex('5a020000'))
        self.assertEqual(result['checkpoint_index'], 1)
        self.assertEqual(runtime.state.memory_bytes, before)
        self.assertEqual(runtime.quick_saves, 1)

    def test_real_new_game_chain_reaches_post_vib_dialogue(self):
        scripts = {script['file']: script for script in IR}
        with (BASE / '数据/台词v74原始工程核查_拆分修复.tsv').open(encoding='utf-8-sig', newline='') as f:
            rows = [normalize_mapping_row(row) for row in csv.DictReader(f, delimiter='\t')]
        rows_by_script = {}
        for row in rows:
            rows_by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
        runtime = NewGameRuntime(TITLES)
        chain = convert_chain(
            scripts, rows_by_script, 'MAC_000.bin', 0x0C,
            {i: f'VOICE_{i:05}.wav' for i in range(215)},
            lambda name: (MAC_DIR / name).read_bytes(), MAC_DIR,
            initial_state=runtime.state, titles=TITLES, runtime=runtime, stop_after=0x2344)
        self.assertEqual(chain['stop']['offset'], 0x2344)
        self.assertEqual(chain['stop']['script'], 'MAC_001.bin')
        self.assertEqual([item['title'] for item in chain['displays']
                          if item['name'] == 'title_disp'],
                         ['杂志彩页上的少女', 'Ｉ´Ｓ・小队結成'])
        self.assertIn(0x2118, [item['offset'] for item in chain['displays']
                                if item['name'] == 'vib_set'])
        self.assertIn(0x2344, [item['offset'] for item in chain['sources']])
        self.assertEqual(runtime.report()['visited_set_count'], 2)
        self.assertNotIn('state_snapshot', runtime.report())
        self.assertEqual(runtime.report()['story_count_status'], 'static_derivation')
        self.assertIn('未取得', runtime.report()['story_count_source']['runtime_write_point'])
        reg17 = [(item['script'], item['offset'], item['operand'])
                 for item in chain['writes']
                 if item.get('operation') == 'reg_calc_17_new_game']
        self.assertEqual(reg17, [('MAC_000.bin', 0x78, 0),
                                 ('MAC_001.bin', 0x58, 1)])
        vib = next(item for item in chain['displays'] if item['name'] == 'vib_set')
        self.assertEqual(vib['raw_hex'], '5710060405010000')
        self.assertEqual(vib['bytes_1_to_5'], [16, 6, 4, 5, 1])


if __name__ == '__main__':
    unittest.main()
