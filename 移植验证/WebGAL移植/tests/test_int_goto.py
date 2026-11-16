"""`int_goto`（0x03）：同一剧本内绝对跳转的解析、接入与真实片段产物。"""
import csv
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import (convert_chain, convert_program, normalize_mapping_row,
                         write_scene_chain)  # noqa: E402
from mac_jump import INT_GOTO, parse_int_goto  # noqa: E402
from mac_state import UnsupportedCommand  # noqa: E402

MAC_ROOT = BASE.parent / '输出-保护边修复/MAC'
IR = BASE / '数据/入口片段.json'
IR_EXTENDED = BASE / '数据/入口片段_扩展候选.json'
MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'
ARTIFACT = BASE / '数据/int_goto片段_MAC001_0x3B94_v74.txt'
REPORT = BASE / '数据/int_goto片段_MAC001_0x3B94_v74.txt.json'
EXT_ARTIFACT = BASE / '数据/int_goto跨剧本片段_MAC001至MAC002_路径修正.txt.json'
EVIDENCE = BASE / '数据/跳转与等待ELF证据.json'


def commands_of(script):
    scripts = json.loads(IR.read_text(encoding='utf-8'))['scripts']
    return next(item for item in scripts if item['file'] == script)['commands']


def rows_of(script):
    with MAPPING.open(encoding='utf-8-sig', newline='') as f:
        return {int(row['指令偏移'], 16): normalize_mapping_row(row)
                for row in csv.DictReader(f, delimiter='\t') if row['剧本'] == script}


class IntGotoParserTests(unittest.TestCase):
    def test_target_is_u32_at_4(self):
        self.assertEqual(parse_int_goto(bytes.fromhex('03000000243c0000')), 0x3C24)
        self.assertEqual(INT_GOTO, 0x03)

    def test_wrong_length_or_opcode_is_rejected(self):
        for raw in ('03000000243c00', '06000000243c0000', '03000000243c000000'):
            with self.subTest(raw=raw), self.assertRaises(UnsupportedCommand):
                parse_int_goto(bytes.fromhex(raw))


class IntGotoExecutionTests(unittest.TestCase):
    def test_forward_goto_skips_commands_and_continues(self):
        commands = [
            {'offset': 0x100, 'name': 'int_goto', 'opcode': 0x03,
             'raw_hex': '0300000010010000'},
            {'offset': 0x108, 'name': 'msg_disp2', 'opcode': 0x60,
             'raw_hex': '60000000000000000000ffff'},
            {'offset': 0x110, 'name': 'msg_disp2', 'opcode': 0x60,
             'raw_hex': '60000000010000000000ffff'},
        ]
        rows = {
            0x108: {'匹配状态': '唯一匹配', '中文（原对照表）': '不应执行',
                    '语音号': '-1', '行号': '1'},
            0x110: {'匹配状态': '唯一匹配', '中文（原对照表）': '跳转后',
                    '语音号': '-1', '行号': '2'},
        }
        lines, sources, _, _, _, _, gotos, stop, *_ = convert_program(commands, rows, 0x100)
        self.assertEqual(lines, ['跳转后;'])
        self.assertEqual([item['offset'] for item in sources], [0x110])
        self.assertEqual([(item['offset'], item['target']) for item in gotos], [(0x100, 0x110)])
        self.assertEqual(stop['reason'], '到达已解析范围末尾')

    def test_target_must_be_a_parsed_command_boundary(self):
        commands = [{'offset': 0x100, 'name': 'int_goto', 'opcode': 0x03,
                     'raw_hex': '0300000010010000'}]
        result = convert_program(commands, {}, 0x100)
        self.assertEqual(result[7]['name'], 'int_goto')
        self.assertIn('不是已解析的命令边界', result[7]['reason'])
        self.assertEqual(result[6], [])

    def test_all_real_targets_are_command_boundaries(self):
        scripts = json.loads(IR_EXTENDED.read_text(encoding='utf-8'))['scripts']
        checked = 0
        for script in scripts:
            offsets = {command['offset'] for command in script['commands']}
            for command in script['commands']:
                if command['opcode'] == INT_GOTO:
                    target = parse_int_goto(bytes.fromhex(command['raw_hex']))
                    self.assertIn(target, offsets, (script['file'], hex(command['offset'])))
                    checked += 1
        self.assertEqual(checked, 835)


class IntGotoRealFragmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        commands = commands_of('MAC_001.bin')
        rows = rows_of('MAC_001.bin')
        voices = {int(row['语音号']): f'VOICE_{int(row["语音号"]):05}.wav'
                  for row in rows.values() if row['语音号'] not in ('-1', '')}
        cls.result = convert_program(commands, rows, 0x3B94, voices,
                                     data=(MAC_ROOT / 'MAC_001.bin').read_bytes(),
                                     emit_waits=True)

    def test_two_real_gotos_are_followed(self):
        lines, sources, _, _, _, _, gotos, stop, *_ = self.result
        self.assertEqual([(item['offset'], item['target']) for item in gotos],
                         [(0x3B94, 0x3C24), (0x3C24, 0x425C)])
        self.assertEqual(len(sources), 87)
        self.assertEqual(len(lines), 89)  # 87 句台词 + 2 条 wait
        self.assertEqual(lines[0], 'wait:1500;')
        self.assertEqual(lines[1], '田中「……说啊。跟她说『只是个采访和抓拍』把她骗过来、强迫她拍泳装照了啊」;')
        self.assertEqual((stop['name'], stop['offset'], stop['raw_hex']),
                         ('ext_goto', 0x51E4, '06000200'))

    def test_artifact_matches_real_execution(self):
        payload = json.loads(REPORT.read_text(encoding='utf-8'))
        self.assertEqual([(item['offset'], item['target'])
                          for item in payload['int_gotos']], [(0x3B94, 0x3C24), (0x3C24, 0x425C)])
        self.assertEqual(len(payload['sources']), 87)
        self.assertEqual((payload['stop']['name'], payload['stop']['offset']),
                         ('ext_goto', 0x51E4))
        lines = ARTIFACT.read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 89)
        self.assertEqual(lines[0], 'wait:1500;')
        self.assertEqual(lines[1], '田中「……说啊。跟她说『只是个采访和抓拍』把她骗过来、强迫她拍泳装照了啊」;')

    def test_evidence_records_handler_and_target_layout(self):
        evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))
        info = evidence['int_goto']
        self.assertEqual(info['handler'], '0x00119590')
        self.assertEqual(info['length'], 8)
        self.assertEqual(info['layout']['target_u32_at_4'], 'u32@4')
        self.assertTrue(info['webgal']['mapped'])
        self.assertIn('ip = script_base + u32@4', info['effect'])


class ExtGotoSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scripts = json.loads(IR.read_text(encoding='utf-8'))['scripts']
        by_file = {script['file']: script for script in scripts}
        rows = {}
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f, delimiter='\t'):
                rows.setdefault(row['剧本'], {})[int(row['指令偏移'], 16)] = normalize_mapping_row(row)
        voices = {int(row['语音号']): f'VOICE_{int(row["语音号"]):05}.wav'
                  for script_rows in rows.values() for row in script_rows.values()
                  if row['语音号'] not in ('-1', '')}
        cls.chain = convert_chain(by_file, rows, 'MAC_001.bin', 0x3B94, voices,
                                  lambda name: (MAC_ROOT / name).read_bytes(), MAC_ROOT, max_gotos=4)

    def test_ext_goto_enters_mac_002_and_stops_at_0x17(self):
        self.assertEqual([(jump['script'], jump['offset'], jump['target_script'], jump['target_entry'])
                          for jump in self.chain['jumps']],
                         [('MAC_001.bin', 0x51E4, 'MAC_002.bin', 0x0C)])
        sequences = self.chain['scene_sequences']
        self.assertEqual([(item['script'], item['start'], len(item['lines'])) for item in sequences],
                         [('MAC_001.bin', 0x3B94, 89), ('MAC_002.bin', 0x0C, 0)])
        stop = sequences[1]['stop']
        self.assertEqual((stop['name'], stop['offset']), ('reg_calc', 0x74))
        self.assertIn('0x00118FD0', stop['reason'])

    def test_scene_files_use_change_scene_and_document_target_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            written = write_scene_chain(self.chain['scene_sequences'], directory)
            self.assertEqual([item['scene'] for item in written],
                             ['mac_001_0x003b94.txt', 'mac_002_0x00000c.txt'])
            parent = (Path(directory) / 'mac_001_0x003b94.txt').read_text(encoding='utf-8').splitlines()
            self.assertEqual(parent[-1], 'changeScene:mac_002_0x00000c.txt;')
            target = (Path(directory) / 'mac_002_0x00000c.txt').read_text(encoding='utf-8')
            self.assertTrue(target.startswith('__commment:MAC_002.bin 0x00000C'))
            self.assertIn('0x000074 的 reg_calc', target)

    def test_artifact_marks_ext_goto_as_mapped_change_scene(self):
        report = json.loads(EXT_ARTIFACT.read_text(encoding='utf-8'))
        self.assertEqual(report['scene_files'][0]['scene'], 'mac_001_0x003b94.txt')
        self.assertEqual(report['jumps'][0]['webgal']['mapped'], True)
        self.assertEqual(report['jumps'][0]['webgal']['command'],
                         'changeScene:mac_002_0x00000c.txt;')

    def test_target_must_be_a_parsed_command_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'MAC_002.bin'
            target.write_bytes(bytes.fromhex('0911006008000000') + struct.pack('<I', 0x0C) + b'\0' * 8)
            scripts = {
                'MAC_001.bin': {'file': 'MAC_001.bin', 'commands': [
                    {'offset': 0, 'name': 'ext_goto', 'opcode': 0x06, 'raw_hex': '06000200'}]},
                'MAC_002.bin': {'file': 'MAC_002.bin', 'commands': [
                    {'offset': 0x100, 'name': 'nop', 'opcode': 0x00, 'raw_hex': '00000000'}]},
            }
            chain = convert_chain(scripts, {}, 'MAC_001.bin', 0, {}, lambda name: b'',
                                  Path(directory), max_gotos=1)
            self.assertEqual(chain['stop']['name'], 'ext_goto_target')
            self.assertIn('不是已解析的命令边界', chain['stop']['reason'])
            self.assertEqual(len(chain['scene_sequences']), 2)
            write_scene_chain(chain['scene_sequences'], Path(directory) / 'scene')
            parent = (Path(directory) / 'scene/mac_001_0x000000.txt').read_text(encoding='utf-8')
            self.assertNotIn('changeScene:', parent)


if __name__ == '__main__':
    unittest.main()
