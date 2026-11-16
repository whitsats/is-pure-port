"""`reg_calc 0x17` 的静态证据、停止行为与不可安全实现的理由。"""
import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program, normalize_mapping_row  # noqa: E402
from mac_state import REG_CALC_17_NOTE, State, UnsupportedCommand, parse_reg_calc  # noqa: E402

MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'
MAC_ROOT = BASE.parent / '输出-保护边修复/MAC'
EVIDENCE = BASE / '数据/reg_calc17ELF证据_修正.json'
SCRIPTS = BASE / '数据/入口片段.json'


class RegCalc17ParserTests(unittest.TestCase):
    def test_0x17_is_refused_with_specific_reason(self):
        with self.assertRaises(UnsupportedCommand) as caught:
            parse_reg_calc(bytes.fromhex('0917010000000000'))
        self.assertEqual(str(caught.exception), REG_CALC_17_NOTE)
        self.assertIn('0x00118FD0', str(caught.exception))
        self.assertIn('运行时表', str(caught.exception))


class RegCalc17BlockingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            rows = {int(r['指令偏移'], 16): normalize_mapping_row(r)
                    for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_001.bin'}
        commands = next(s for s in json.loads(SCRIPTS.read_text(encoding='utf-8'))['scripts']
                        if s['file'] == 'MAC_001.bin')['commands']
        cls.result = convert_program(commands, rows, 0x0C, {},
                                     data=(MAC_ROOT / 'MAC_001.bin').read_bytes())

    def test_target_stops_at_0x58_without_writing_state(self):
        lines, sources, _, _, writes, _, _, stop, *_ = self.result
        self.assertEqual((lines, sources), ([], []))
        self.assertEqual((stop['name'], stop['offset']), ('reg_calc', 0x58))
        self.assertIn('0x00118FD0', stop['reason'])
        self.assertFalse(any(w['offset'] == 0x58 for w in writes))

    def test_evidence_records_tables_and_gaps(self):
        evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))
        self.assertEqual(evidence['command']['handler'], '0x00118FD0')
        self.assertEqual(evidence['dispatch']['entry_0x17'], '0x00118FD0')
        path = evidence['observed_path']
        self.assertEqual(path['read_bit']['table'], '0x00A98C50')
        self.assertEqual(path['second_call']['bit_table'], '0x00A98C50')
        self.assertEqual(path['second_call']['on_all_set'], '0x001174B8(3)')
        self.assertIn('输入编号', path['state_writes'][0]['value'])
        self.assertEqual(path['second_call']['count_source'], '0x00B1EC20')
        self.assertEqual(path['scene_table']['table_pointer'], '0x00B25554')
        self.assertEqual([w['address'] for w in path['state_writes']],
                         ['0x00118FE0', '0x00118FEC'])
        self.assertEqual(evidence['script_scan']['occurrences'], 84)
        self.assertEqual(evidence['script_scan']['scripts'], 58)
        self.assertEqual(evidence['script_scan']['mac_058_operands'], [0, 1, 2, 3, 4])
        self.assertTrue(evidence['next_material'])

    def test_operand_matches_script_index(self):
        scripts = json.loads(SCRIPTS.read_text(encoding='utf-8'))['scripts']
        found = []
        for script in scripts:
            for command in script['commands']:
                raw = bytes.fromhex(command['raw_hex'])
                if command['opcode'] == 9 and len(raw) == 8 and raw[1] == 0x17:
                    found.append((script['file'], command['offset'], raw[2] | (raw[3] << 8)))
        self.assertEqual(len(found), 84)
        for script, offset, operand in found:
            if script == 'MAC_058.bin':
                self.assertIn(operand, (0, 1, 2, 3, 4))
            else:
                self.assertEqual(operand, int(script[4:7]), (script, hex(offset)))
        self.assertIn(('MAC_001.bin', 0x58, 1), found)


if __name__ == '__main__':
    unittest.main()
