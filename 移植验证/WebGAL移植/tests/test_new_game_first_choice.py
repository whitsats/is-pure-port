import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_chain
from 验证新游戏首选项 import analyze


class FirstChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = analyze()

    def test_opening_reaches_real_first_choice_with_expected_progress(self):
        opening = self.report['opening']
        self.assertEqual(opening['dialogues'], 520)
        self.assertEqual((opening['stop']['script'], opening['stop']['offset']), ('MAC_001.bin', 0x3878))
        self.assertEqual(opening['visited_bits'], '0300000000000000')
        self.assertEqual(self.report['choice']['visible_indices'], [0, 1, 2])
        self.assertEqual(self.report['result_register'], '0x6007')

    def test_branches_keep_actual_opening_state_and_reach_next_choice(self):
        branches = self.report['branches']
        self.assertEqual([b['dialogues'] for b in branches], [127, 110, 98])
        self.assertEqual([b['first_taken_condition']['target'] for b in branches], [0x38C4, 0x3C2C, 0x40B8])
        for index, branch in enumerate(branches):
            self.assertEqual(branch['state_bytes_at_stop']['0022E'], index)
            self.assertEqual(branch['visited_bits_after'], '0700000000000000')
            self.assertEqual((branch['stop']['script'], branch['stop']['offset'], branch['stop']['name']),
                             ('MAC_002.bin', 0xA8, 'sel_disp4'))
        self.assertEqual(branches[0]['state_bytes_at_stop']['00422'] & 1, 1)
        self.assertEqual(branches[1]['state_bytes_at_stop'].get('00422', 0) & 1, 0)

    def test_chain_passes_configured_step_limit(self):
        commands = [{'offset': 0, 'opcode': 9, 'name': 'reg_calc', 'raw_hex': '0900004001000000'},
                    {'offset': 8, 'opcode': 255, 'name': 'unknown', 'raw_hex': 'ff000000'}]
        scripts = {'test.bin': {'commands': commands}}
        def run(limit):
            return convert_chain(scripts, {}, 'test.bin', 0, {}, lambda _: b'', BASE, max_steps=limit)['stop']
        self.assertIn('超过 1 步上限', run(1)['reason'])
        self.assertEqual(run(2)['reason'], '未转换的指令')


if __name__ == '__main__':
    unittest.main()
