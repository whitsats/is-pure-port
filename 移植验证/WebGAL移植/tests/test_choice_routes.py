import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program, normalize_mapping_row
from mac_reader import ROOT
from mac_jump import parse_ext_goto
from mac_state import State


class ChoiceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = BASE / '数据'
        scripts = json.loads((directory / '入口片段.json').read_text(encoding='utf-8'))['scripts']
        cls.commands = next(s['commands'] for s in scripts if s['file'] == 'MAC_001.bin')
        cls.next_commands = next(s['commands'] for s in scripts if s['file'] == 'MAC_002.bin')
        cls.data = (ROOT / '输出-保护边修复/MAC/MAC_001.bin').read_bytes()
        cls.next_data = (ROOT / '输出-保护边修复/MAC/MAC_002.bin').read_bytes()
        with (directory / '三版译文与汉化盘核查_补字码.tsv').open(encoding='utf-8-sig', newline='') as f:
            rows = [normalize_mapping_row(r) for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_001.bin']
        cls.rows = {int(r['指令偏移'], 16): r for r in rows}
        cls.voices = {}
        for name in ('语音校验_MAC001_语音215至230.json', '语音校验_MAC001_语音231至281.json'):
            for entry in json.loads((directory / name).read_text(encoding='utf-8'))['entries']:
                cls.voices[entry['id']] = f"VOICE_{entry['id']:05}.wav"

    def test_three_return_values_reach_candidate_targets_and_converge(self):
        for value, target, dialogues in ((0, 0x38C4, 124), (1, 0x3C2C, 107), (2, 0x40B8, 95)):
            with self.subTest(value=value):
                state = State()
                state.write(0x6007, value)
                output, sources, pacing, decisions, writes, displays, gotos, stop, reads, sounds, fades, waits = \
                    convert_program(self.commands, self.rows, 0x3884, self.voices,
                                    state=state, data=self.data, emit_waits=True)
                self.assertEqual(next(d['target'] for d in decisions if d['result']), target)
                self.assertEqual(len(sources), dialogues)
                self.assertEqual((stop['name'], stop['offset']), ('ext_goto', 0x51E4))
                if value == 0:
                    self.assertTrue(any(w['dest'].get('raw') == '0xA010' and w['after'] == 1 for w in writes))
                jump = parse_ext_goto(bytes.fromhex(stop['raw_hex']), ROOT / '输出-保护边修复/MAC')
                self.assertEqual((jump['target_script'], jump['target_entry']), ('MAC_002.bin', 0x0C))
                next_result = convert_program(self.next_commands, {}, jump['target_entry'], self.voices,
                                              state=state, data=self.next_data, emit_waits=True)
                self.assertEqual((next_result[7]['name'], next_result[7]['offset']), ('reg_calc', 0x74))


if __name__ == '__main__':
    unittest.main()
