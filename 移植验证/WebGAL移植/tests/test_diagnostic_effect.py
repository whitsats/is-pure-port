import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program

RAW = '6a00010100004000f6ff000000000c000c000c000600020000000000000000000000000000000000'


class DiagnosticEffectTests(unittest.TestCase):
    def test_default_stops_and_opt_in_marks_omission(self):
        commands = [{'offset': 0, 'opcode': 0x6A, 'name': 'effect_start', 'raw_hex': RAW},
                    {'offset': 40, 'opcode': 0xFF, 'name': 'unknown', 'raw_hex': 'ff000000'}]
        strict = convert_program(commands, {}, 0)
        self.assertEqual((strict[7]['offset'], strict[7]['name']), (0, 'effect_start'))
        diagnostic = convert_program(commands, {}, 0, diagnostic_effects=True)
        self.assertEqual(diagnostic[7]['offset'], 40)
        self.assertEqual(diagnostic[5][0]['name'], 'diagnostic_effect_start_omitted')
        self.assertIn('不可作为等价', diagnostic[5][0]['reason'])

    def test_different_effect_parameters_are_not_skipped(self):
        cmd = {'offset': 0, 'opcode': 0x6A, 'name': 'effect_start', 'raw_hex': RAW[:-2] + '01'}
        result = convert_program([cmd], {}, 0, diagnostic_effects=True)
        self.assertEqual(result[7]['offset'], 0)
        self.assertIn('只允许', result[7]['reason'])


if __name__ == '__main__':
    unittest.main()
