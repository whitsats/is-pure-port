"""`time_wait` 与 `ext_goto` 的解析、链式转换和产物一致性。"""
import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_chain, convert_program, normalize_mapping_row  # noqa: E402
from mac_jump import parse_ext_goto  # noqa: E402
from mac_state import State, UnsupportedCommand  # noqa: E402
from mac_wait import parse_time_wait  # noqa: E402

MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'
MAC_ROOT = BASE.parent / '输出-保护边修复/MAC'
OPENING = BASE / '数据/开头程序转换_跨MAC001_至0x58_v74.txt'
OPENING_JSON = BASE / '数据/开头程序转换_跨MAC001_至0x58_v74.txt.json'
RAW_BYTES = BASE / '数据/开头片段原字节_跨MAC001_至0x58.json'
EVIDENCE = BASE / '数据/跳转与等待ELF证据.json'


class WaitJumpParserTests(unittest.TestCase):
    def test_time_wait_mode_1_is_2000_ms(self):
        detail = parse_time_wait(bytes.fromhex('0c017800'), State())
        self.assertEqual((detail['mode'], detail['frames'], detail['duration_ms']), (1, 120, 2000))
        self.assertEqual(detail['command'], 'wait:2000;')
        self.assertTrue(detail['webgal']['mapped'])

    def test_unproven_time_wait_mode_stops(self):
        with self.assertRaises(UnsupportedCommand):
            parse_time_wait(bytes.fromhex('0c000100'), State())

    def test_ext_goto_resolves_group_zero_target(self):
        detail = parse_ext_goto(bytes.fromhex('06000100'), MAC_ROOT)
        self.assertEqual((detail['group'], detail['index']), (0, 1))
        self.assertEqual((detail['target_script'], detail['target_entry']), ('MAC_001.bin', 0x0C))
        self.assertEqual(detail['unused_bytes'], '00')
        self.assertTrue(detail['webgal']['mapped'] is False)

    def test_unproven_ext_goto_group_stops(self):
        with self.assertRaises(UnsupportedCommand):
            parse_ext_goto(bytes.fromhex('06000010'), MAC_ROOT)


class OpeningChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            all_rows = [normalize_mapping_row(r) for r in csv.DictReader(f, delimiter='\t')]
        cls.rows_by_script = {}
        for row in all_rows:
            cls.rows_by_script.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = row
        cls.scripts = {s['file']: s for s in json.loads(
            (BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']}
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in all_rows if r['语音号'] not in ('-1', '')}
        cache = {}

        def loader(name):
            if name not in cache:
                cache[name] = (MAC_ROOT / name).read_bytes()
            return cache[name]

        cls.chain = convert_chain(cls.scripts, cls.rows_by_script, 'MAC_000.bin', 0x88,
                                  voices, loader, MAC_ROOT)

    def test_single_segment_crosses_time_wait_and_stops_at_ext_goto(self):
        commands = self.scripts['MAC_000.bin']['commands']
        rows = self.rows_by_script['MAC_000.bin']
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in rows.values() if r['语音号'] not in ('-1', '')}
        lines, sources, _, _, _, _, _, stop, _, _, _, waits = convert_program(
            commands, rows, 0x88, voices, data=(MAC_ROOT / 'MAC_000.bin').read_bytes())
        self.assertEqual((len(lines), len(sources)), (74, 74))
        self.assertEqual((stop['name'], stop['offset']), ('ext_goto', 0x73C))
        self.assertEqual(waits[0]['command'], 'wait:2000;')

    def test_chain_records_jump_and_follows_target(self):
        chain = self.chain
        self.assertEqual((len(chain['sources']), len(chain['waits'])), (74, 1))
        self.assertIn('wait:2000;', chain['lines'])
        self.assertEqual(len(chain['segments']), 2)
        self.assertEqual((chain['segments'][1]['script'], chain['segments'][1]['start']),
                         ('MAC_001.bin', 0x0C))
        self.assertEqual((chain['stop']['script'], chain['stop']['name'], chain['stop']['offset']),
                         ('MAC_001.bin', 'reg_calc', 0x58))
        self.assertEqual(len(chain['jumps']), 1)
        jump = chain['jumps'][0]
        self.assertEqual((jump['script'], jump['offset'], jump['target_script'], jump['target_entry']),
                         ('MAC_000.bin', 0x73C, 'MAC_001.bin', 0x0C))
        self.assertTrue(jump['webgal']['mapped'] is False)
        self.assertTrue(any(e['script'] == 'MAC_001.bin' for e in chain['sounds']))
        self.assertTrue(any(e['script'] == 'MAC_001.bin' for e in chain['reads']))

    def test_generated_artifact_and_raw_bytes(self):
        lines = OPENING.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 75)
        self.assertEqual(lines.count('wait:2000;'), 1)
        self.assertFalse(any(line.startswith('jump:') for line in lines))
        payload = json.loads(OPENING_JSON.read_text(encoding='utf-8'))
        self.assertEqual(len(payload['sources']), 74)
        self.assertEqual(len(payload['wait_events']), 1)
        self.assertEqual(len(payload['jumps']), 1)
        self.assertEqual(payload['segments'][1]['script'], 'MAC_001.bin')
        self.assertEqual(payload['stop']['offset'], 0x58)
        self.assertEqual(payload['stop']['name'], 'reg_calc')
        self.assertEqual(payload['stop']['raw_hex'], '0917010000000000')
        self.assertEqual(payload['stop']['script'], 'MAC_001.bin')
        self.assertIn('0x00118FD0', payload['stop']['reason'])
        self.assertIn('运行时表', payload['stop']['reason'])
        raw = json.loads(RAW_BYTES.read_text(encoding='utf-8'))
        self.assertEqual(len(raw['segments']), 2)
        self.assertEqual(len(raw['commands']), 247)
        self.assertEqual(raw['segments'][0]['script'], 'MAC_000.bin')
        self.assertEqual(raw['segments'][1]['start'], '0x000C')
        self.assertEqual(raw['segments'][1]['commands'][-1]['offset'], '0x0058')

    def test_evidence_records_handlers_and_unknowns(self):
        evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))
        self.assertEqual(evidence['time_wait']['handler'], '0x00119258')
        self.assertEqual(evidence['time_wait']['parameters']['u16_at_2']['read_at'],
                         '0x001192BC/0x001192C4')
        self.assertEqual(evidence['ext_goto']['handler'], '0x001196B8')
        self.assertEqual(evidence['ext_goto']['target_probe']['entry'], '0x00000C')
        self.assertTrue(evidence['ext_goto']['webgal']['mapped'] is False)
        self.assertTrue(evidence['unknowns'])


if __name__ == '__main__':
    unittest.main()
