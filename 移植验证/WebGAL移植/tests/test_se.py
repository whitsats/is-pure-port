"""SE 段（`0x3A/0x3C/0x3D/0x3E/0x3F`）的解码、证据与“音频未映射”的约定。

钉住三件事：
1. 五条指令的操作数读取点与写入偏移（来自反汇编，地址写死会被断言校验）；
2. 两张运行时表的来源（模块头 `+0x40`/`+0x74` 加装载基址）与装载路径（`init.bin` → `0xA54700`），
   以及“表里没有文件名”这一事实，所以产物不能出现任何猜出来的音频路径；
3. 转换结果：`MAC_000` 开头 74 句、五处 SE 五连块与一处 `se_del`，停在 `0x730` `time_wait`。
"""
import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
PROJECT = BASE.parent
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(PROJECT))
import MAC_命令表提取 as common                     # noqa: E402
import 状态字证据 as ev                             # noqa: E402
from emit_webgal import convert_program, normalize_mapping_row  # noqa: E402
from mac_se import (CHANNEL_BASE, CHANNEL_BYTES, CHANNEL_FIELDS, HANDLERS, MODULE_LOAD,
                    SE_DEL, SE_REQ, SE_SET, SE_SPEED, SE_VOL, SE_WAIT, parse_se_req, parse_se_set,
                    parse_se_speed, parse_se_vol, parse_se_wait)  # noqa: E402
from mac_state import UnsupportedCommand            # noqa: E402

EVIDENCE = BASE / '数据/SE段ELF证据.json'
OPENING = BASE / '数据/开头程序转换_越0x730_v74.txt'
OPENING_JSON = BASE / '数据/开头程序转换_越0x730_v74.txt.json'
RAW_BYTES = BASE / '数据/开头片段原字节_MAC000_越0x730.json'
MAC = PROJECT / '输出-保护边修复/MAC/MAC_000.bin'
MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'


class ParseTests(unittest.TestCase):
    def test_speed_and_volume(self):
        speed = parse_se_speed(bytes.fromhex('3e000100'))
        self.assertEqual((speed['channel'], speed['speed']), (0, 1))
        self.assertEqual(speed['writes'][f'0x{CHANNEL_FIELDS["speed"]:X}'], 1)
        volume = parse_se_vol(bytes.fromhex('3f008000'))
        self.assertEqual((volume['channel'], volume['volume']), (0, 0x80))

    def test_volume_rejects_high_byte(self):
        with self.assertRaises(UnsupportedCommand):
            parse_se_vol(bytes.fromhex('3f008001'))

    def test_set_needs_staging_code(self):
        with self.assertRaises(UnsupportedCommand):
            parse_se_set(bytes.fromhex('3a000000'), None)
        detail = parse_se_set(bytes.fromhex('3a000000'), 0x5003)
        self.assertEqual(detail['staged_code'], '0x5003')
        self.assertEqual(detail['sample_index'], 3)
        with self.assertRaises(UnsupportedCommand):
            parse_se_set(bytes.fromhex('3a000100'), 0x5003)

    def test_request_and_wait(self):
        request = parse_se_req(bytes.fromhex('3c000200'))
        self.assertEqual((request['channel'], request['parameter']), (0, 2))
        self.assertEqual(request['writes'][f'0x{CHANNEL_FIELDS["state"]:X}'], 2)
        wait = parse_se_wait(bytes.fromhex('3d000100'))
        self.assertEqual((wait['channel'], wait['parameter']), (0, 1))
        self.assertTrue(wait['blocks_in_original'])
        self.assertFalse(wait['waited'])
        with self.assertRaises(UnsupportedCommand):
            parse_se_req(bytes.fromhex('3c000001'))


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = common.ELF.read_bytes()
        cls.segs = ev.segments(cls.data)
        cls.dis = ev.Dis(cls.data, cls.segs)
        cls.table = common.load_table(cls.data)
        cls.evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))

    def instruction(self, address):
        ins = self.dis.read(address, 4)[0]
        return f'{ins["mnemonic"]} {ins["op"]}'

    def test_handlers_match_the_command_table(self):
        for opcode, address in HANDLERS.items():
            self.assertEqual(self.table[opcode]['handler'], address, hex(opcode))
            self.assertEqual(self.evidence['handlers'][f'0x{opcode:02X}']['handler'], f'0x{address:X}')

    def test_channel_structure_constants(self):
        self.assertEqual(CHANNEL_BASE, 0x3F480)
        self.assertEqual(CHANNEL_BYTES, 12)
        self.assertEqual(CHANNEL_FIELDS, {'code': 0x0, 'volume': 0x2, 'previous_volume': 0x3,
                                          'state': 0x5, 'counter': 0x6, 'speed': 0x8})
        self.assertEqual(self.evidence['channel']['base'], '0x3F480')

    def test_table_pointers_come_from_the_module_header(self):
        self.assertEqual(self.instruction(0x103AD4), 'sw $v1, 0x88($a2)')
        self.assertEqual(self.instruction(0x103AA0), 'lw $a0, 0x38($s1)')
        self.assertEqual(self.instruction(0x103C20), 'sw $a1, 0x6b90($v1)')
        self.assertEqual(self.evidence['table_writers']['byte_table'], '0x00103AD4（模块头 +0x40）')
        self.assertEqual(self.evidence['table_writers']['handle_table'], '0x00103C20（模块头 +0x74）')

    def test_module_is_loaded_from_init_bin(self):
        self.assertEqual(self.instruction(0x108C00), 'lui $s1, 0xd7')
        self.assertEqual(self.instruction(0x108C08), 'addiu $s1, $s1, 0x2980')
        self.assertEqual(self.instruction(0x108C1C), 'jal 0x101468')
        self.assertEqual(self.instruction(0x108C20), 'addiu $a0, $zero, 8')
        self.assertEqual(self.instruction(0x108C24), 'jal 0x1035d8')
        offset = ev.vaddr_to_offset(self.segs, 0x258190, 9)
        self.assertEqual(self.data[offset:offset + 9], b'init.bin\0')
        self.assertEqual(MODULE_LOAD['init'], '0x1035D8(0x00A54700)')

    def test_start_playback_path_has_no_file_name(self):
        # se_set 起播走 0x1173E8：只调 0x1053C0 并遍历 0x68C4/0x68C8 的记录表。
        self.assertEqual(self.instruction(0x11740C), 'jal 0x1053c0')
        self.assertEqual(self.instruction(0x11741C), 'lw $v0, 0x68c8($v1)')
        self.assertEqual(self.instruction(0x117424), 'lw $a0, 0x68c4($v1)')

    def test_script_wide_distribution(self):
        stats = self.evidence['scripts']
        self.assertEqual(stats['total'], 13618)
        self.assertEqual(stats['five_instruction_blocks'], 2187)
        self.assertEqual(stats['per_opcode'], {'0x3E': 2947, '0x3F': 2361, '0x3A': 2327,
                                               '0x3C': 2946, '0x3D': 3037})
        requests = {int(item['value'], 16): item['count'] for item in stats['requests']}
        self.assertEqual(requests[2], 2321)
        channels = {int(item['value'], 16): item['count'] for item in stats['channels']}
        self.assertEqual(channels[0], 9423)


class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            rows = {int(r['指令偏移'], 16): normalize_mapping_row(r)
                    for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_000.bin'}
        commands = next(s for s in json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
                        if s['file'] == 'MAC_000.bin')['commands']
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in rows.values() if r['语音号'] not in ('-1', '')}
        (cls.lines, cls.sources, _, _, _, _, _, cls.stop, cls.reads, cls.sounds,
         cls.fades, _) = convert_program(commands, rows, 0x88, voices, data=MAC.read_bytes())

    def test_se_blocks_are_consumed(self):
        self.assertEqual([(s['offset'], s['name']) for s in self.sounds[:15]], [
            (0x224, 'se_speed'), (0x228, 'se_vol'), (0x22C, 'se_set'), (0x230, 'se_req'), (0x234, 'se_wait'),
            (0x260, 'se_speed'), (0x264, 'se_vol'), (0x268, 'se_set'), (0x26C, 'se_req'), (0x270, 'se_wait'),
            (0x318, 'se_speed'), (0x31C, 'se_vol'), (0x320, 'se_set'), (0x324, 'se_req'), (0x328, 'se_wait')])
        self.assertEqual([(s['offset'], s['name']) for s in self.sounds[15:25]], [
            (0x514, 'se_speed'), (0x518, 'se_vol'), (0x51C, 'se_set'), (0x520, 'se_req'), (0x524, 'se_wait'),
            (0x548, 'se_speed'), (0x54C, 'se_vol'), (0x550, 'se_set'), (0x554, 'se_req'), (0x558, 'se_wait')])
        self.assertEqual([(s['offset'], s['name']) for s in self.sounds[25:]], [
            (0x720, 'se_speed'), (0x724, 'se_req'), (0x728, 'se_wait'), (0x72C, 'se_del')])
        self.assertTrue(all(s['webgal']['mapped'] is False for s in self.sounds))
        self.assertTrue(all(s['channel'] in (0, 2) for s in self.sounds))

    def test_se_set_uses_the_staged_sample_numbers(self):
        sets = [s for s in self.sounds if s['name'] == 'se_set']
        self.assertEqual([s['staged_code'] for s in sets], ['0x5000', '0x5003', '0x5001', '0x5065', '0x5063'])
        self.assertEqual([s['sample_index'] for s in sets], [0, 3, 1, 0x65, 0x63])

    def test_se_run_continues_through_the_first_36_lines(self):
        self.assertEqual(len(self.lines), 74)
        self.assertEqual([s['offset'] for s in self.sources[23:25]], [0x238, 0x24C])
        self.assertIn('回过神来时', self.lines[23])
        self.assertEqual((self.stop['name'], self.stop['offset']), ('ext_goto', 0x73C))

    def test_no_audio_paths_are_invented(self):
        text = OPENING.read_text(encoding='utf-8')
        self.assertNotIn('playEffect', text)
        self.assertNotIn('SE_', text)
        payload = json.loads(OPENING_JSON.read_text(encoding='utf-8'))
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn('playEffect', blob)
        self.assertNotIn('SE_0', blob)
        self.assertEqual(len(payload['se_events']), 29)
        self.assertTrue(all(e['webgal']['mapped'] is False for e in payload['se_events']))

    def test_raw_bytes_cover_every_sound_offset(self):
        raw = json.loads(RAW_BYTES.read_text(encoding='utf-8'))
        picked = {int(c['offset'], 16): c for c in raw['commands']}
        expect = {0x224: ('se_speed', '3e000100'), 0x228: ('se_vol', '3f008000'),
                  0x22C: ('se_set', '3a000000'), 0x230: ('se_req', '3c000200'),
                  0x234: ('se_wait', '3d000100'), 0x358: ('fade_start', '68801e00ff0f0000'),
                  0x72C: ('se_del', '3b020000'), 0x730: ('time_wait', '0c017800')}
        for offset, (name, raw_hex) in expect.items():
            self.assertEqual((picked[offset]['name'], picked[offset]['raw_hex']), (name, raw_hex))
        self.assertEqual(len(raw['commands']), 231)


if __name__ == '__main__':
    unittest.main()
