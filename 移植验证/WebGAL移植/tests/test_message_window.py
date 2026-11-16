import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_message_window_run, convert_run, normalize_mapping_row
import 消息窗证据


def rows_for(script):
    with (BASE / '数据/三版译文与汉化盘核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        selected = [r for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == script]
    return {int(row['指令偏移'], 16): normalize_mapping_row(row) for row in selected}


def commands_of(script):
    data = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
    return next(s for s in data if s['file'] == script)['commands']


def cmd(offset, opcode, name, raw_hex=''):
    return {'offset': offset, 'opcode': opcode, 'name': name, 'raw_hex': raw_hex}


class MessageWindowConvertTests(unittest.TestCase):
    def setUp(self):
        self.commands = [
            cmd(0x10, 0x60, 'msg_disp2', '60000000000000000100ffff'),
            cmd(0x1C, 0x12, 'msg_view', '12030000'),
            cmd(0x20, 0x1A, 'msg_wait', '1a000000'),
            cmd(0x24, 0x1B, 'msg_clear', '1b000000'),
            cmd(0x28, 0x60, 'msg_disp2', '60000000000000000200ffff'),
            cmd(0x34, 0x33, 'graph_disp', '3301000054070000'),
        ]
        self.rows = {
            0x10: {'匹配状态': '唯一匹配', '中文（原对照表）': '第一句。', '语音号': '-1', '行号': '1'},
            0x28: {'匹配状态': '唯一匹配', '中文（原对照表）': '第二句。', '语音号': '-1', '行号': '2'},
        }

    def test_crosses_pacing_commands_and_keeps_them_in_report(self):
        lines, sources, pacing, stop = convert_message_window_run(self.commands, self.rows, 0x10)
        self.assertEqual(lines, ['第一句。;', '第二句。;'])
        self.assertEqual([p['name'] for p in pacing], ['msg_view', 'msg_wait', 'msg_clear'])
        self.assertTrue(all(p['emitted'] is False for p in pacing))
        self.assertEqual(stop['name'], 'graph_disp')
        self.assertEqual([s['offset'] for s in sources], [0x10, 0x28])

    def test_old_mode_still_stops_at_view(self):
        lines, _, stop = convert_run(self.commands, self.rows, 0x10)
        self.assertEqual(lines, ['第一句。;'])
        self.assertEqual(stop['name'], 'msg_view')

    def test_pacing_without_preceding_text_is_recorded_but_not_emitted(self):
        # msg_view/msg_wait/msg_clear 既不新增文本也不等按键（0x00119D68 才读手柄），
        # 所以 clear 之后再来一轮只记进 pacing，并标出当时窗口里没有新台词。
        lines, _, pacing, stop = convert_message_window_run(self.commands, self.rows, 0x1C)
        self.assertEqual(lines, ['第二句。;'])
        self.assertEqual([p['name'] for p in pacing], ['msg_view', 'msg_wait', 'msg_clear'])
        self.assertTrue(all(p['text_since_clear'] is False for p in pacing))
        self.assertEqual(stop['name'], 'graph_disp')

    def test_unknown_view_parameter_stops(self):
        self.commands[1]['raw_hex'] = '12020000'
        lines, _, _, stop = convert_message_window_run(self.commands, self.rows, 0x10)
        self.assertEqual(lines, ['第一句。;'])
        self.assertIn('msg_view 参数', stop['reason'])

    def test_text_after_clear_needs_own_mapping(self):
        self.rows[0x10]['匹配状态'] = '重复匹配'
        self.assertEqual(convert_message_window_run(self.commands, self.rows, 0x10)[0], [])


class RealScriptTests(unittest.TestCase):
    def test_opening_now_passes_msg_view_and_stops_at_conditional(self):
        lines, sources, pacing, stop = convert_message_window_run(
            commands_of('MAC_000.bin'), rows_for('MAC_000.bin'), 0x88, {0: 'VOICE_00000.wav'})
        self.assertEqual(len(lines), 2)
        self.assertEqual([p['name'] for p in pacing], ['msg_view', 'msg_wait', 'msg_clear'])
        self.assertEqual(stop['name'], 'if')
        self.assertEqual(stop['offset'], 0xAC)
        self.assertEqual([s['line'] for s in sources], [0, 1])

    def test_unverified_voice_still_stops_the_run(self):
        lines, _, _, stop = convert_message_window_run(
            commands_of('MAC_003.bin'), rows_for('MAC_003.bin'), 0x2548)
        self.assertEqual(lines, [])
        self.assertIn('语音', stop['reason'])

    def test_verified_voice_run_with_trailing_pacing(self):
        voices = {voice: f'VOICE_{voice:05}.wav' for voice in (1124, 1125, 1126, 1127)}
        lines, sources, pacing, stop = convert_message_window_run(
            commands_of('MAC_005.bin'), rows_for('MAC_005.bin'), 0x1BC4, voices)
        self.assertEqual(len(lines), 22)
        self.assertTrue(lines[0].endswith('-VOICE_01124.wav;'))
        self.assertEqual([p['name'] for p in pacing], ['msg_view', 'msg_wait', 'msg_clear'])
        self.assertEqual([s['voice'] for s in sources if s['voice'] != -1], [1124, 1125, 1126, 1127])
        self.assertEqual(stop['name'], 'fade_start')


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import MAC_命令表提取 as common
        data = common.ELF.read_bytes()
        table = common.load_table(data)
        cls.facts = 消息窗证据.scan(data, 消息窗证据.segments(data), table)

    def test_only_display_command_reads_pad_bit_while_pacing_commands_do_not(self):
        self.assertEqual(len(self.facts['0x60']['pad_bit_0x2000_reads']), 1)
        for opcode in ('0x12', '0x1A', '0x1B'):
            self.assertEqual(self.facts[opcode]['pad_bit_0x2000_reads'], [])

    def test_display_command_state_tables_are_resolved(self):
        command = self.facts['0x60']
        self.assertEqual(len(command['command_state_jump_table']['entries']), 8)
        self.assertEqual(len(command['window_state_jump_table']['entries']), 10)
        self.assertEqual(command['command_state_jump_table']['entries'][0], '0x00119DC0')

    def test_clear_resets_window_record(self):
        targets = [call['target'] for call in self.facts['0x1B']['direct_calls']]
        self.assertIn('0x00122D18', targets)


if __name__ == '__main__':
    unittest.main()
