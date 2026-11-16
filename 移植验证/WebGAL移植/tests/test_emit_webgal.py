import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '转换器'))
from emit_webgal import convert_run, normalize_mapping_row


class EmitTests(unittest.TestCase):
    def setUp(self):
        self.commands = [{'offset': 12, 'opcode': 0x60, 'name': 'msg_disp2'},
                         {'offset': 24, 'opcode': 0x02, 'name': 'if'}]
        self.rows = {12: {'匹配状态': '唯一匹配', '中文（原对照表）': '第一句。', '语音号': '-1', '行号': '0'}}

    def test_stops_before_unknown_control_flow(self):
        lines, source, stop = convert_run(self.commands, self.rows, 12)
        self.assertEqual(lines, ['第一句。;'])
        self.assertEqual(source[0]['offset'], 12)
        self.assertEqual(stop['offset'], 24)

    def test_missing_or_ambiguous_rows_stop(self):
        self.rows[12]['匹配状态'] = '重复匹配'
        self.assertEqual(convert_run(self.commands, self.rows, 12)[0], [])

    def test_voice_does_not_silently_disappear(self):
        self.rows[12]['语音号'] = '0'
        self.assertIn('语音', convert_run(self.commands, self.rows, 12)[2]['reason'])

    def test_verified_voice_is_emitted(self):
        self.rows[12]['语音号'] = '0'
        lines, sources, stop = convert_run(self.commands, self.rows, 12, {0: 'VOICE_00000.wav'})
        self.assertEqual(lines, ['第一句。 -VOICE_00000.wav;'])
        self.assertEqual(sources[0]['voice'], 0)
        self.assertEqual(stop['offset'], 24)

    def test_unsafe_text_is_rejected(self):
        self.rows[12]['中文（原对照表）'] = '甲;乙'
        self.assertEqual(convert_run(self.commands, self.rows, 12)[0], [])

    def test_address_matched_v74_text_wins_over_byte_exact_v7(self):
        row = {'汇总文本对盘': '不一致', '汇总中文': '汇总译文',
               'v7.4工程文本对盘': '不一致', 'v7.4工程中文': 'v7.4 译文',
               'v7工程文本对盘': '逐字节一致', 'v7工程中文': 'v7 译文'}
        normalized = normalize_mapping_row(row)
        self.assertEqual(normalized['中文（原对照表）'], 'v7.4 译文')
        self.assertEqual(normalized['匹配状态'], '唯一匹配')
        self.assertIn('v7.4', normalized['译文来源'])
        # 对盘结果只作证据保留，不参与选译。
        self.assertEqual(normalized['对盘状态'], 'v7.4工程=不一致；汇总=不一致；v7=逐字节一致')
        row['v7.4工程中文'] = ''
        missing = normalize_mapping_row(row)
        self.assertEqual(missing['匹配状态'], '没有 v7.4 地址对应译文')
        self.assertEqual(missing['中文（原对照表）'], '')


if __name__ == '__main__':
    unittest.main()
