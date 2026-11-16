from pathlib import Path
import json
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_chain, convert_program
from mac_state import State
from mac_title_table import (DEFAULT_TITLE_MANIFEST, TITLE_DISP, TITLE_RECORD_COUNT,
                             load_title_manifest, load_title_table, resolve_title_disp)


def title_cmd(offset=0, raw='50000000'):
    return {'offset': offset, 'opcode': TITLE_DISP, 'name': 'title_disp', 'raw_hex': raw}


class StaticTitleTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_title_table()

    def test_counts_and_static_boundary_are_proven(self):
        self.assertEqual(self.table['record_count'], TITLE_RECORD_COUNT)
        self.assertEqual(len(self.table['records']), 57)
        self.assertEqual(self.table['next_record_first_pointer'], '0x00000000')
        self.assertEqual(self.table['records'][0]['title'], '杂志彩页上的少女')
        self.assertEqual(self.table['records'][1]['title'], 'Ｉ´Ｓ・小队結成')
        self.assertEqual(self.table['records'][56]['title'], 'Ｉ´ｓ')
        self.assertTrue(all(record['webgal_safe'] for record in self.table['records']))

    def test_original_and_v74_sources_are_recorded(self):
        self.assertTrue(self.table['v74_source'].endswith('init-v5-lazy.bin'))
        self.assertTrue(self.table['original_source'].endswith('init.bin.bin'))
        self.assertEqual(self.table['record_count'], len(self.table['records']))
        self.assertTrue(all(record['original']['same_pointer_layout']
                            for record in self.table['records']))

    def test_unknown_code_substitutions_are_explicit(self):
        record = self.table['records'][1]
        self.assertEqual(record['unknown_codes'], [])
        self.assertEqual(record['title'], 'Ｉ´Ｓ・小队結成')
        self.assertEqual(record['substitutions'][0]['code'], '8145')
        self.assertIn('8145', record['title_raw_hex'].replace(' ', ''))

    def test_manifest_round_trip(self):
        table = load_title_manifest(DEFAULT_TITLE_MANIFEST)
        self.assertEqual(table['record_count'], 57)
        self.assertEqual(table['records'][1]['title'], 'Ｉ´Ｓ・小队結成')


class TitleDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = load_title_manifest(DEFAULT_TITLE_MANIFEST)['records']

    def test_title_disp_uses_g440_index_and_g4b0_parameter(self):
        state = State()
        state.write_context_u32(0x440, 1)
        state.write_context_u32(0x4B0, 1)
        result = convert_program([title_cmd(), {'offset': 4, 'opcode': 0xFF,
                                                'name': 'stop', 'raw_hex': 'ff000000'}],
                                 {}, 0, state=state, titles=self.records)
        self.assertEqual(result[0], ['intro:Ｉ´Ｓ・小队結成;'])
        detail = result[5][0]
        self.assertEqual((detail['index'], detail['display_parameter']), (1, 7))
        self.assertEqual(detail['webgal']['mapped'], True)
        self.assertEqual(result[7]['offset'], 4)

    def test_missing_table_and_out_of_range_stop_without_output(self):
        state = State()
        state.write_context_u32(0x440, TITLE_RECORD_COUNT)
        result = convert_program([title_cmd()], {}, 0, state=state, titles=self.records)
        self.assertEqual(result[0], [])
        self.assertIn('超出静态标题表', result[7]['reason'])
        result = convert_program([title_cmd()], {}, 0, state=State())
        self.assertEqual(result[0], [])
        self.assertIn('需要静态章节标题表', result[7]['reason'])

    def test_bad_parameter_and_unsafe_title_are_rejected(self):
        state = State()
        with self.assertRaises(Exception):
            resolve_title_disp(b'\x50\x01\x00\x00', state, self.records)
        unsafe = [dict(self.records[0], title='bad;title', webgal_safe=False)]
        result = convert_program([title_cmd()], {}, 0, state=state, titles=unsafe)
        self.assertEqual(result[0], [])
        self.assertIn('不安全', result[7]['reason'])

    def test_chain_passes_title_table_and_keeps_scene_line(self):
        state = State()
        state.write_context_u32(0x440, 0)
        commands = [title_cmd(), {'offset': 4, 'opcode': 0xFF,
                                  'name': 'stop', 'raw_hex': 'ff000000'}]
        chain = convert_chain({'MAC_TEST.bin': {'file': 'MAC_TEST.bin', 'commands': commands}},
                              {}, 'MAC_TEST.bin', 0, {}, lambda name: b'', BASE,
                              initial_state=state, titles=self.records)
        self.assertEqual(chain['lines'], ['intro:杂志彩页上的少女;'])
        self.assertEqual(chain['stop']['offset'], 4)
        self.assertEqual(chain['scene_sequences'][0]['lines'], ['intro:杂志彩页上的少女;'])


if __name__ == '__main__':
    unittest.main()
