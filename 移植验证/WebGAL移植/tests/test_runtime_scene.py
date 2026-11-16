import hashlib
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_runtime_scene import (OPERANDS, collect_operands, compile_range, continuation,
                               load_commands, load_rows, scan_blockers)
from mac_release import ENGINEERING_DIALOGUE
from mac_state import UnsupportedCommand
from mac_webgal_state import emit_word_write

CONTINUATION_SHA256 = '79eaa304593a3d6e45d9e83dfd1a9053584f6bfec2d5f5bde088eef6fa949863'


class ContinuationCompatibility(unittest.TestCase):
    """第三组选项之后的既有区间必须保持逐字节一致。"""

    def test_existing_range_is_byte_identical(self):
        lines, voices = continuation()
        text = '\n'.join(lines) + '\n'
        self.assertEqual(len(lines), 326)
        self.assertEqual(len(voices), 64)
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), CONTINUATION_SHA256)

    def test_generic_entry_reproduces_existing_range(self):
        result = compile_range('MAC_003.bin', 0x24D0, end=0x34AC, words=OPERANDS, strict=True,
                               rows=load_rows('MAC_003.bin', ENGINEERING_DIALOGUE))
        self.assertEqual(result.lines, continuation()[0])
        self.assertEqual((result.stop.offset, result.stop.name, result.stop.category),
                         (0x34AC, 'sel_disp4', 'choice'))

    def test_default_compilation_prefers_disc_build_dialogue(self):
        result = compile_range('MAC_003.bin', 0x24D0, end=0x34AC, words=OPERANDS, strict=True)
        line = next(line for line in result.lines if 'VOICE_00551.wav' in line)
        self.assertTrue(line.startswith('伊织「'))
        self.assertIn('向她表个白，她', line)
        self.assertEqual(result.used_voices, continuation()[1])

    def test_start_must_be_a_command_boundary(self):
        with self.assertRaises(ValueError):
            compile_range('MAC_003.bin', 0x24D1, words=OPERANDS)


class OperandDerivation(unittest.TestCase):
    def test_range_derivation_covers_words_the_fixed_list_missed(self):
        derived = collect_operands(load_commands('MAC_003.bin'), 0x34B8)
        for operand in (0x6010, 0x6014, 0x601A, 0xA013):
            self.assertIn(operand, derived)
        self.assertTrue(set(OPERANDS) <= set(derived) | set(OPERANDS))

    def test_word_and_bit_sharing_one_byte_is_rejected(self):
        # 0x6010 是 bank1 字（偏移 0x240..0x241）；0x8200 是 bank0 位（偏移 0x240）。
        commands = [
            {'offset': 0x10, 'name': 'reg_calc', 'raw_hex': '0900106001000000'},
            {'offset': 0x18, 'name': 'reg_calc', 'raw_hex': '0900008201000000'},
        ]
        with self.assertRaises(ValueError):
            collect_operands(commands)

    def test_distinct_bits_in_one_byte_are_allowed(self):
        commands = [
            {'offset': 0x10, 'name': 'reg_calc', 'raw_hex': '0900128001000000'},
            {'offset': 0x18, 'name': 'reg_calc', 'raw_hex': '0900138001000000'},
        ]
        self.assertEqual(collect_operands(commands), (0x8012, 0x8013))


class BatchCompile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = compile_range('MAC_003.bin', 0x34B8)

    def test_compiles_past_fourth_choice_up_to_fifth(self):
        self.assertGreater(len(self.result.lines), 1000)
        self.assertEqual((self.result.stop.offset, self.result.stop.name),
                         (0x5A44, 'sel_disp4'))
        self.assertEqual(self.result.stop.category, 'choice')

    def test_labels_match_jump_targets(self):
        labels = set(self.result.labels)
        text = '\n'.join(self.result.lines)
        imported = {int(token[len('jumpLabel:mac_'):].split(' ')[0].rstrip(';'), 16)
                    for token in text.splitlines() if token.startswith('jumpLabel:mac_')}
        self.assertEqual(imported - labels, set())
        self.assertEqual(sorted(labels), sorted(self.result.targets))
        self.assertFalse(self.result.unresolved_targets)

    def test_measured_state_writes_are_tracked(self):
        writes = [line for line in self.result.lines if line.startswith('setVar:')]
        self.assertTrue(writes)
        for line in writes:
            name = line.split('setVar:')[1].split('=')[0]
            self.assertTrue(name.startswith('mac_'), line)

    def test_mac004_inventory_is_categorised(self):
        scan = scan_blockers('MAC_004.bin', 0x0C)
        counts = {entry['category']: entry['count'] for entry in scan['blockers']}
        # 0x5C 的 reg_calc 0x17、0x68 的 title_disp、0xA38 的选项都已接线，不再计入阻塞。
        self.assertEqual(counts, {'choice': 1, 'effect': 17, 'cross_script': 2})
        self.assertEqual(scan['blocker_total'], 20)
        self.assertEqual([w['offset'] for w in scan['wired']], ['0xA38'])
        effect = next(entry for entry in scan['blockers'] if entry['category'] == 'effect')
        self.assertEqual(effect['offsets'][0], '0x1AA8')
        self.assertTrue(all(entry['note'] for entry in scan['blockers']))

    def test_blocking_choice_is_not_emitted(self):
        self.assertNotIn('choose:', '\n'.join(self.result.lines))


class WebGalArithmetic(unittest.TestCase):
    def test_mul_normalises_through_modulo(self):
        lines = emit_word_write(bytes.fromhex('0903196019600000'), (0x6019,), 't')
        self.assertEqual(lines[0], 'setVar:mac_6019=((mac_6019)*(mac_6019))%(65536) -next;')
        self.assertIn('jumpLabel:wrap_t_underflow -when=mac_6019<-32768;', lines)
        self.assertIn('jumpLabel:wrap_t_overflow -when=mac_6019>32767;', lines)

    def test_div_truncates_toward_zero(self):
        lines = emit_word_write(bytes.fromhex('0904196010000000'), (0x6019,), 't')
        self.assertEqual(lines[0], 'setVar:mac_6019=((mac_6019)-((mac_6019)%(16)))/(16) -next;')

    def test_mod_is_emitted_directly(self):
        lines = emit_word_write(bytes.fromhex('0905196010000000'), (0x6019,), 't')
        self.assertEqual(lines[0], 'setVar:mac_6019=(mac_6019)%(16) -next;')

    def test_bit_operations_are_still_refused(self):
        for opcode in ('06', '07'):
            with self.assertRaises(UnsupportedCommand):
                emit_word_write(bytes.fromhex('09' + opcode + '196010000000'), (0x6019,), 't')


if __name__ == '__main__':
    unittest.main()
