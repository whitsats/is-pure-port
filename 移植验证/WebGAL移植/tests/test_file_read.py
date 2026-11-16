"""`file_read`/`file_wait` 的语义证据与转换结果。

这些用例把 0x21C 的调查钉住：分派（命令表第一字段）、操作数读取点、组 5 没有描述表
因而“不发起任何读取”、staging 槽位、以及全盘 2321 条都是同一形态。它们同时把
“转换停在 0x224 的 se_speed”写成断言，避免以后有人把未实现的 SE 段当成已完成。
"""
import csv
import json
import struct
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]          # 移植验证/WebGAL移植
PROJECT = BASE.parent                               # 移植验证
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(PROJECT))
import MAC_命令表提取 as common                     # noqa: E402
import 状态字证据 as ev                             # noqa: E402
from emit_webgal import convert_program, normalize_mapping_row  # noqa: E402
from mac_file_read import (GROUP_FIVE_HANDLER, GROUP_FIVE_RETURN, GROUP_JUMP_TABLE, SE_AFS_ROW,
                           STAGED_CODE, STAGED_FLAG, SUPPORTED_GROUP, SUPPORTED_PREFIX,
                           SUPPORTED_STYLE, parse_file_read, parse_file_wait)  # noqa: E402
from mac_state import UnsupportedCommand            # noqa: E402

EVIDENCE = BASE / '数据/文件读取ELF证据.json'
OPENING = BASE / '数据/开头程序转换_越0x730_v74.txt'
OPENING_JSON = BASE / '数据/开头程序转换_越0x730_v74.txt.json'
RAW_BYTES = BASE / '数据/开头片段原字节_MAC000_越0x730.json'
PREVIOUS = BASE / '数据/开头程序转换_越0x1EC.txt'
PREVIOUS_JSON = BASE / '数据/开头程序转换_越0x1EC.txt.json'
MAC = PROJECT / '输出-保护边修复/MAC/MAC_000.bin'
MAPPING = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'


def disassemble():
    data = common.ELF.read_bytes()
    segs = ev.segments(data)
    return data, segs, ev.Dis(data, segs)


class CommandFormTests(unittest.TestCase):
    def test_operand_bytes(self):
        detail = parse_file_read(bytes.fromhex('0f000050'))
        self.assertEqual(detail['style'], SUPPORTED_STYLE)
        self.assertEqual(detail['code'], '0x5000')
        self.assertEqual(detail['group'], SUPPORTED_GROUP)
        self.assertEqual(detail['index'], 0)
        self.assertEqual(detail['webgal']['mapped'], False)

    def test_other_groups_and_styles_are_rejected(self):
        for raw in ('0f000030', '0f005000', '0f010050'):
            with self.assertRaises(UnsupportedCommand):
                parse_file_read(bytes.fromhex(raw))

    def test_file_wait_parameter(self):
        self.assertEqual(parse_file_wait(bytes.fromhex('10000000'))['parameter'], 0)
        with self.assertRaises(UnsupportedCommand):
            parse_file_wait(bytes.fromhex('10000200'))


class DispatchEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.segs, cls.dis = disassemble()
        cls.table = common.load_table(cls.data)
        cls.evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))

    def test_handler_addresses_come_from_the_command_table(self):
        self.assertEqual(self.table[0x0F]['handler'], 0x119878)
        self.assertEqual(self.table[0x10]['handler'], 0x1198E0)
        self.assertEqual(self.table[0x0F]['bytes'], 4)
        self.assertEqual(self.table[0x10]['bytes'], 4)
        self.assertEqual(self.evidence['file_read']['handler'], '0x119878')

    def test_handler_reads_style_and_code_then_advances(self):
        handler = self.dis.read(0x119878, 0x64)
        read_operands = [(i['at'], i['mnemonic'], i['op']) for i in handler
                         if i['mnemonic'] in ('lbu', 'lhu') and i['at'] in ('0x00119890', '0x00119898')]
        self.assertEqual(read_operands, [('0x00119890', 'lbu', '$a0, 1($v1)'),
                                         ('0x00119898', 'lhu', '$a1, 2($v1)')])
        ops = {(i['mnemonic'], i['op']) for i in handler}
        self.assertIn(('jal', '0x12d980'), ops)
        # ip += 4 只出现在 0x1198AC..0x1198B4 这一段（只有读取返回 0 才走过来）。
        self.assertIn(('addiu', '$v0, $v0, 4'), ops)

    def test_group_five_has_no_description_table(self):
        jump = ev.table_at(self.data, self.segs, GROUP_JUMP_TABLE, 8)
        self.assertEqual(jump[SUPPORTED_GROUP], GROUP_FIVE_HANDLER)
        code = [(i['mnemonic'], i['op']) for i in self.dis.read(GROUP_FIVE_HANDLER, 0x10)]
        self.assertEqual(code[0], ('addiu', '$s0, $zero, 5'))
        self.assertEqual(code[1], ('move', '$a2, $zero'))
        self.assertIn(('beql', '$a2, $zero, 0x12d970'), code)
        self.assertEqual(self.evidence['group_jump_table']['group_5'], f'0x{GROUP_FIVE_HANDLER:X}')
        # 组 5 分支里没有任何 exit/jal/syscall：不拼名、不发起读取。
        self.assertFalse([i for i in self.dis.read(0x12D8B8, 0x10)
                          if i['mnemonic'] in ('jal', 'jalr', 'syscall')])
        self.assertEqual(self.evidence['group_jump_table']['return_0'], f'0x{GROUP_FIVE_RETURN:X}')

    def test_staging_slot_write_and_poll(self):
        writer = [i for i in self.dis.read(0x12D9EC, 0x30)]
        self.assertIn('sb $a0, 0x51f8($at)', [f'{i["mnemonic"]} {i["op"]}' for i in writer])
        poller = [f'{i["mnemonic"]} {i["op"]}' for i in self.dis.read(0x12DA44, 0x74)]
        self.assertIn('lbu $v1, 0x51f8($v1)', poller)
        self.assertIn('sw $v0, 0x51fc($at)', poller)
        self.assertEqual(self.evidence['staging']['flag'], f'0x{STAGED_FLAG:X}')
        self.assertEqual(self.evidence['staging']['code'], f'0x{STAGED_CODE:X}')

    def test_all_scripts_use_the_same_form(self):
        stats = self.evidence['scripts']
        self.assertEqual(stats['prefixes'], [f'0x{SUPPORTED_PREFIX:02X}'])
        self.assertEqual(stats['file_reads'], stats['followed_by_file_wait'])
        self.assertEqual(stats['min_code'], '0x5000')
        self.assertEqual(stats['max_code'], '0x5097')
        self.assertEqual(stats['distinct_codes'], 152)
        self.assertEqual(stats['file_reads'], 2321)

    def test_se_afs_row_is_identified_but_not_mapped(self):
        row = self.evidence['se_afs']
        self.assertEqual(row['at'], f'0x{SE_AFS_ROW:X}')
        self.assertEqual(row['name'], 'se.afs')
        self.assertEqual(row['index'], SUPPORTED_GROUP)
        self.assertEqual(row['size_hex'], '0x45C980')
        self.assertEqual(row['entries_in_iso'], 174)
        # 152 种编号落在 174 个条目之内，但这只是相容，不是对应关系。
        self.assertLess(stats_max(stats=self.evidence), row['entries_in_iso'])

    def test_original_slot_bytes_are_read_from_the_script(self):
        raw = MAC.read_bytes()
        self.assertEqual(raw[0x21C:0x220].hex(), '0f000050')
        self.assertEqual(raw[0x220:0x224].hex(), '10000000')
        self.assertEqual(raw[0x224:0x228].hex(), '3e000100')


def stats_max(stats):
    return int(stats['scripts']['max_code'], 16) & 0xFFF


class ConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with MAPPING.open(encoding='utf-8-sig', newline='') as f:
            rows = {int(r['指令偏移'], 16): normalize_mapping_row(r)
                    for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_000.bin'}
        data = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
        commands = next(s for s in data if s['file'] == 'MAC_000.bin')['commands']
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in rows.values() if r['语音号'] not in ('-1', '')}
        (cls.lines, cls.sources, _, _, _, _, _, cls.stop, cls.reads, cls.sounds,
         cls.fades, _) = convert_program(commands, rows, 0x88, voices, data=MAC.read_bytes())

    def test_stops_at_ext_goto_not_at_file_read(self):
        self.assertEqual(self.stop['offset'], 0x73C)
        self.assertEqual(self.stop['name'], 'ext_goto')
        self.assertEqual(len(self.lines), 74)
        self.assertEqual(self.sources[-1]['offset'], 0x6C8)

    def test_reads_are_recorded_without_output(self):
        self.assertEqual([(r['offset'], r['name']) for r in self.reads],
                         [(0x21C, 'file_read'), (0x220, 'file_wait'),
                          (0x258, 'file_read'), (0x25C, 'file_wait'),
                          (0x310, 'file_read'), (0x314, 'file_wait'),
                          (0x50C, 'file_read'), (0x510, 'file_wait'),
                          (0x540, 'file_read'), (0x544, 'file_wait')])
        self.assertEqual([r['code'] for r in self.reads if r['name'] == 'file_read'],
                         ['0x5000', '0x5003', '0x5001', '0x5065', '0x5063'])
        self.assertTrue(all(r['webgal']['mapped'] is False for r in self.reads))

    def test_generated_artifacts_match(self):
        lines = [line for line in OPENING.read_text(encoding='utf-8').split('\n') if line]
        self.assertEqual(lines, self.lines)
        payload = json.loads(OPENING_JSON.read_text(encoding='utf-8'))
        self.assertEqual(payload['stop']['offset'], 0x730)
        self.assertEqual([r['name'] for r in payload['file_reads']],
                         ['file_read', 'file_wait'] * 5)
        self.assertEqual(payload['mapping'].replace('\\', '/'), '数据/三版译文与汉化盘核查_补字码.tsv')
        self.assertIn('v7.4', payload['translation_source'])
        # 三句 v7 独有译文必须换成按地址对应的 v7.4 最终译文。
        self.assertIn('伊织「能借着演戏去体验各种不同的人生，我觉得很开心」 -VOICE_00000.wav;', lines)
        self.assertIn('一贵「你说什么！？你明明已经有喜欢的女生了吧！」 -VOICE_00015.wav;', lines)
        self.assertIn('寺谷「呃啊啊啊——」 -VOICE_00016.wav;', lines)
        raw = json.loads(RAW_BYTES.read_text(encoding='utf-8'))
        self.assertEqual((raw['start'], raw['end']), ('0x0088', '0x0744'))
        picked = {c['offset']: c['raw_hex'] for c in raw['commands']}
        self.assertEqual(picked['0x021C'], '0f000050')
        self.assertEqual(picked['0x0220'], '10000000')
        self.assertEqual(picked['0x0224'], '3e000100')
        self.assertEqual(picked['0x0358'], '68801e00ff0f0000')
        self.assertEqual(len(raw['commands']), 231)

    def test_superseded_artifact_covers_the_same_leading_offsets(self):
        # 0x1EC 旧产物停在当时缺 v7 译文的行；现在按地址取的 v7.4 译文补齐，
        # 现在继续越过淡入淡出、停在 0x730。文本选择已变，
        # 但两段产物的前 23 个来源偏移必须一致。
        lines = [line for line in PREVIOUS.read_text(encoding='utf-8').split('\n') if line]
        old = json.loads(PREVIOUS_JSON.read_text(encoding='utf-8'))
        self.assertEqual(len(lines), 23)
        self.assertEqual([s['offset'] for s in old['sources']],
                         [s['offset'] for s in self.sources[:len(lines)]])
        self.assertGreater(len(self.lines), len(lines))


if __name__ == '__main__':
    unittest.main()
