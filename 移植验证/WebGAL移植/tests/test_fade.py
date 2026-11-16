"""`fade_start` / `fade_wait` / `se_del` 的解析与真实片段记账。"""
import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program, normalize_mapping_row  # noqa: E402
from mac_fade import parse_fade_start, parse_fade_wait  # noqa: E402
from mac_se import parse_se_del  # noqa: E402
from mac_state import State, UnsupportedCommand  # noqa: E402

MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'
MAC = BASE.parent / '输出-保护边修复/MAC/MAC_000.bin'
OPENING = BASE / '数据/开头程序转换_越0x730_v74.txt'
OPENING_JSON = BASE / '数据/开头程序转换_越0x730_v74.txt.json'


class FadeParserTests(unittest.TestCase):
    def test_white_fade_and_duration(self):
        detail = parse_fade_start(bytes.fromhex('68801e00ff0f0000'), State())
        self.assertEqual((detail['direction'], detail['duration']), ('fade_out', 30))
        self.assertEqual((detail['color'], detail['rgb']), ('0xFFF', [255, 255, 255]))
        self.assertEqual(detail['color_source'], 'specified')
        self.assertTrue(detail['webgal']['mapped'] is False)

    def test_reuse_needs_a_previous_color(self):
        with self.assertRaises(UnsupportedCommand):
            parse_fade_start(bytes.fromhex('687f1e0000f00000'), State())
        detail = parse_fade_start(bytes.fromhex('687f1e0000f00000'), State(), 0xFFF)
        self.assertEqual((detail['direction'], detail['color_source'], detail['rgb']),
                         ('fade_in', 'reuse', [255, 255, 255]))

    def test_black_and_zero_duration_clamp(self):
        detail = parse_fade_start(bytes.fromhex('6880000000000000'), State())
        self.assertEqual(detail['duration'], 1)
        self.assertEqual(detail['rgb'], [0, 0, 0])
        self.assertEqual(detail['color'], '0x000')

    def test_generated_evidence_matches_the_parsers(self):
        payload = json.loads((BASE / '数据/淡入淡出ELF证据.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['fade_start']['length'], 8)
        self.assertEqual(payload['fade_wait']['length'], 4)
        self.assertEqual(payload['fade_start']['transition_table']['entry_0'],
                         {'word_0': 20, 'word_1': 21, 'type': 0})
        self.assertEqual(payload['se_del']['advance']['bytes'], 4)
        self.assertTrue(payload['unknowns'])

    def test_wait_and_se_del(self):
        wait = parse_fade_wait(bytes.fromhex('69000000'))
        self.assertTrue(wait['blocks_in_original'])
        self.assertFalse(wait['waited'])
        delete = parse_se_del(bytes.fromhex('3b020000'))
        self.assertEqual(delete['channel'], 2)
        self.assertFalse(delete['webgal']['mapped'])
        for raw in ('6901', '3b020001', '68000000000000'):
            with self.assertRaises(UnsupportedCommand):
                if raw.startswith('69'):
                    parse_fade_wait(bytes.fromhex(raw))
                elif raw.startswith('3b'):
                    parse_se_del(bytes.fromhex(raw))
                else:
                    parse_fade_start(bytes.fromhex(raw), State())


class RealFadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            rows = {int(r['指令偏移'], 16): normalize_mapping_row(r)
                    for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_000.bin'}
        commands = next(s for s in json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
                        if s['file'] == 'MAC_000.bin')['commands']
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in rows.values() if r['语音号'] not in ('-1', '')}
        (cls.lines, cls.sources, _, _, _, _, _, cls.stop, _, cls.sounds,
         cls.fades, _) = convert_program(commands, rows, 0x88, voices, data=MAC.read_bytes())

    def test_fourteen_fades_are_recorded(self):
        starts = [f for f in self.fades if f['name'] == 'fade_start']
        waits = [f for f in self.fades if f['name'] == 'fade_wait']
        self.assertEqual((len(starts), len(waits)), (14, 14))
        self.assertEqual([(f['offset'], f['direction']) for f in starts[:4]],
                         [(0x358, 'fade_out'), (0x374, 'fade_in'),
                          (0x398, 'fade_out'), (0x3B4, 'fade_in')])
        self.assertEqual((starts[0]['duration'], starts[0]['rgb']), (30, [255, 255, 255]))
        self.assertEqual((starts[-1]['offset'], starts[-1]['duration'], starts[-1]['rgb']),
                         (0x714, 1, [0, 0, 0]))
        self.assertTrue(all(f['webgal']['mapped'] is False for f in self.fades))
        self.assertTrue(all(w['waited'] is False for w in waits))

    def test_run_crosses_time_wait_to_ext_goto_and_se_del_is_accounted(self):
        self.assertEqual(len(self.lines), 74)
        self.assertEqual((self.stop['name'], self.stop['offset']), ('ext_goto', 0x73C))
        self.assertEqual([(s['offset'], s['name']) for s in self.sounds[-4:]],
                         [(0x720, 'se_speed'), (0x724, 'se_req'),
                          (0x728, 'se_wait'), (0x72C, 'se_del')])

    def test_artifacts_contain_no_invented_fade_or_audio(self):
        text = OPENING.read_text(encoding='utf-8')
        for token in ('fadeIn', 'fadeOut', 'playEffect', 'setTransition'):
            self.assertNotIn(token, text)
        payload = json.loads(OPENING_JSON.read_text(encoding='utf-8'))
        self.assertEqual(len(payload['fade_events']), 28)
        self.assertEqual(payload['fade_evidence'], '数据/淡入淡出ELF证据.json')
        self.assertTrue(all(f['webgal']['mapped'] is False for f in payload['fade_events']))


if __name__ == '__main__':
    unittest.main()
