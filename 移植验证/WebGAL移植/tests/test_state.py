import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_state import (State, UnsupportedCommand, apply_reg_calc, evaluate_if,
                       parse_if, parse_reg_calc, to_s16)
from emit_webgal import convert_program, normalize_mapping_row
import mac_display
from mac_display import parse_graph_disp, parse_msg_mode, resolve_graph_records
import 状态字证据


def rows_for(script):
    with (BASE / '数据/三版译文与汉化盘核查.tsv').open(encoding='utf-8-sig', newline='') as f:
        selected = [r for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == script]
    return {int(row['指令偏移'], 16): normalize_mapping_row(row) for row in selected}


def voices_of(rows):
    return {int(row['语音号']): f'VOICE_{int(row["语音号"]):05}.wav'
            for row in rows.values() if row['语音号'] not in ('-1', '')}


def commands_of(script):
    data = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
    return next(s for s in data if s['file'] == script)['commands']


class OperandTests(unittest.TestCase):
    def test_operand_classes_and_offsets_follow_elf_arithmetic(self):
        state = State()
        # 0x600E：bank 位 0x2000 置位，kind 0x4000 → bank1 word #14
        self.assertEqual(state.address_of(0x600E), ('word', 1, 14))
        self.assertEqual(state.offset_of('word', 1, 14), 0x220 + 14 * 2)
        # 0xA01A：kind 0x8000 → bank1 bit #26
        self.assertEqual(state.address_of(0xA01A), ('bit', 1, 26))
        self.assertEqual(state.offset_of('bit', 1, 26), 0x220 + 0x200 + 26 // 8)
        # 无 kind 位的是立即数，按 16 位有符号解释
        self.assertEqual(state.address_of(0x0001)[0], 'value')
        self.assertEqual(state.read(0x0001), 1)
        self.assertEqual(state.read(0xFFFF), -1)

    def test_unwritten_state_reads_zero_and_writes_are_signed_16_bit(self):
        state = State()
        self.assertEqual(state.read(0x600E), 0)
        old, new = state.write(0x600E, 0x1FFFF)
        self.assertEqual((old, new), (0, -1))
        self.assertEqual(state.read(0x600E), -1)
        self.assertEqual(to_s16(0x8000), -32768)

    def test_combined_kind_bits_fall_through_to_immediate(self):
        # 0x115744/0x115750 只认 0x4000、0x8000，0xC000 落到 0x115758 的 `move $a1, $a0`。
        state = State()
        self.assertEqual(state.address_of(0xC001)[0], 'value')
        self.assertEqual(state.read(0xC001), -16383)
        self.assertEqual(state.read(0xFFFF), -1)

    def test_bit_writes_use_low_bit_and_share_word_storage(self):
        state = State()
        state.write(0x6101, 0x20)
        self.assertEqual(state.read(0xA015), 1)
        self.assertEqual(state.write(0xA015, 2), (1, 0))
        self.assertEqual(state.read(0x6101), 0)
        self.assertEqual(state.write(0xA015, -1), (0, 1))
        self.assertEqual(state.read(0x6101), 0x20)
        with self.assertRaises(UnsupportedCommand):
            state.write(1, 1)


class ConditionTests(unittest.TestCase):
    def instruction(self, lhs, rhs, code, target=0xD0):
        import struct
        raw = bytearray(16)
        raw[0] = 0x02
        struct.pack_into('<I', raw, 4, target)
        struct.pack_into('<HH', raw, 8, lhs, rhs)
        raw[12] = code
        return bytes(raw)

    def test_all_six_verified_comparisons(self):
        cases = [
            (0, 5, 5, True), (0, 5, 6, False),
            (1, 5, 6, True), (1, 5, 5, False),
            (2, 5, 5, True), (2, 6, 5, False),
            (3, 5, 5, True), (3, 4, 5, False),
            (4, 4, 5, True), (4, 5, 5, False),
            (5, 6, 5, True), (5, 5, 5, False),
        ]
        for code, left, right, expected in cases:
            result, target, detail = evaluate_if(self.instruction(left, right, code), State())
            self.assertEqual(result, expected, f'比较码 {code}：{left} {detail["operator"]} {right}')
            self.assertEqual(target, 0xD0)

    def test_unverified_forms_are_rejected(self):
        raw = bytearray(self.instruction(1, 0, 0))
        raw[12] = 6
        with self.assertRaises(UnsupportedCommand):
            parse_if(bytes(raw))
        raw = bytearray(self.instruction(1, 0, 0))
        raw[1] = 8
        with self.assertRaises(UnsupportedCommand):
            parse_if(bytes(raw))
        with self.assertRaises(UnsupportedCommand):
            parse_if(self.instruction(1, 0, 0)[:12])

    def test_condition_reads_state_words(self):
        state = State()
        state.write(0x600E, 7)
        result, _, detail = evaluate_if(self.instruction(0x600E, 7, 0), state)
        self.assertTrue(result)
        self.assertEqual(detail['lhs_value'], 7)
        self.assertEqual(detail['lhs']['offset'], 0x220 + 14 * 2)


class RegCalcTests(unittest.TestCase):
    def raw(self, op, dst, src):
        import struct
        data = bytearray(8)
        data[0] = 0x09
        data[1] = op
        struct.pack_into('<HH', data, 2, dst, src)
        return bytes(data)

    def test_assign_add_sub(self):
        state = State()
        entry = apply_reg_calc(self.raw(0, 0x600E, 1), state)
        self.assertEqual((entry['operation'], entry['before'], entry['after']), ('assign', 0, 1))
        apply_reg_calc(self.raw(1, 0x6026, 0x600E), state)   # word38 += 1
        self.assertEqual(state.read(0x6026), 1)
        apply_reg_calc(self.raw(2, 0x6026, 5), state)        # word38 -= 5
        self.assertEqual(state.read(0x6026), -4)

    def test_multiply_divide_modulo_and_bitwise(self):
        state = State()
        state.write(0x6026, 7)
        state.write(0x6030, 9)
        apply_reg_calc(self.raw(3, 0x6030, 0x6026), state)   # 9 * 7
        self.assertEqual(state.read(0x6030), 63)
        state.write(0x6032, 9)
        apply_reg_calc(self.raw(4, 0x6032, 0x6026), state)   # 9 / 7
        self.assertEqual(state.read(0x6032), 1)
        state.write(0x6034, 9)
        apply_reg_calc(self.raw(5, 0x6034, 0x6026), state)   # 9 % 7
        self.assertEqual(state.read(0x6034), 2)
        state.write(0x6036, 9)
        apply_reg_calc(self.raw(6, 0x6036, 0x6026), state)   # 9 & 7
        self.assertEqual(state.read(0x6036), 1)
        state.write(0x6038, 9)
        apply_reg_calc(self.raw(7, 0x6038, 0x6026), state)   # 9 | 7
        self.assertEqual(state.read(0x6038), 15)
        state.write(0x603A, 9)
        apply_reg_calc(self.raw(0x0F, 0x603A, 0x6026), state)
        self.assertEqual(state.read(0x603A), 16)

    def test_signed_division_truncates_toward_zero(self):
        state = State()
        state.write(0x6026, 7)
        state.write(0x6030, -9)
        state.write(0x6032, -9)
        apply_reg_calc(self.raw(4, 0x6030, 0x6026), state)
        apply_reg_calc(self.raw(5, 0x6032, 0x6026), state)
        self.assertEqual(state.read(0x6030), -1)
        self.assertEqual(state.read(0x6032), -2)
        with self.assertRaises(UnsupportedCommand):
            apply_reg_calc(self.raw(4, 0x6030, 0x6034), state)

    def test_store_immediate(self):
        state = State()
        entry = apply_reg_calc(self.raw(0x0E, 0x600E, 0xFFFF), state)
        self.assertEqual((entry['operation'], entry['source']['value'], entry['after']),
                         ('store_imm', -1, -1))
        self.assertEqual(state.read(0x600E), -1)

    def test_convert_program_uses_the_new_operations(self):
        commands = [
            {'offset': 0x100, 'name': 'reg_calc', 'opcode': 0x09,
             'raw_hex': '0903004001400000'},
            {'offset': 0x108, 'name': 'reg_calc', 'opcode': 0x09,
             'raw_hex': '090e004001000000'},
        ]
        state = State()
        state.write(0x4000, 6)
        state.write(0x4001, 7)
        result = convert_program(commands, {}, 0x100, {}, state=state)
        writes, stop = result[4], result[7]
        self.assertEqual([entry['operation'] for entry in writes], ['mul', 'store_imm'])
        self.assertEqual(state.read(0x4000), 1)  # 先 6*7=42，再被立即数 1 覆盖
        self.assertEqual(stop['reason'], '到达已解析范围末尾')

    def test_unsupported_operation_stops(self):
        with self.assertRaises(UnsupportedCommand):
            apply_reg_calc(self.raw(0x12, 0x600E, 1), State())
        with self.assertRaises(UnsupportedCommand):
            parse_reg_calc(self.raw(23, 0x600E, 1))

    def test_remaining_memory_random_and_table_operations_are_refused(self):
        for op in (8, 9, 0x0B, 0x0C, 0x10, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17):
            with self.subTest(op=hex(op)), self.assertRaises(UnsupportedCommand):
                apply_reg_calc(self.raw(op, 0x600E, 1), State())


class MsgModeTests(unittest.TestCase):
    def test_modes_five_and_six_are_explained(self):
        five = parse_msg_mode(bytes.fromhex('13050000'))
        six = parse_msg_mode(bytes.fromhex('13060000'))
        self.assertEqual((five['mode'], five['geometry']['x'], five['geometry']['y'],
                          five['geometry']['w'], five['geometry']['h'], five['geometry']['lines']),
                         (5, 0xAE, 0x158, 0x23C, 0x4E, 0xB))
        self.assertEqual((six['mode'], six['geometry']['x'], six['geometry']['aux']), (6, 0x4A, 0x1EC))
        self.assertTrue(five['mode_byte_written'])
        self.assertFalse(six['mode_byte_written'])  # 0x00122EF4 跳过 sb
        self.assertIn('不改显隐', five['summary'])

    def test_unverified_modes_and_lengths_are_rejected(self):
        for raw in ('13070000', '13000000', '1305', '12030000'):
            with self.assertRaises(UnsupportedCommand):
                parse_msg_mode(bytes.fromhex(raw))

    def test_trailing_bytes_are_recorded_not_rejected(self):
        # 处理函数只读 ip[1]（0x0011A6D0/D4），所以 2、3 字节照原样记录。
        detail = parse_msg_mode(bytes.fromhex('13050102'))
        self.assertEqual(detail['unused_bytes'], '0102')


class GraphDispTests(unittest.TestCase):
    def setUp(self):
        self.data = (BASE.parent / '输出-保护边修复/MAC/MAC_000.bin').read_bytes()

    def test_parameters_and_record_resolution(self):
        detail = parse_graph_disp(bytes.fromhex('3301010054070000'))
        self.assertEqual((detail['count'], detail['flag'], detail['blob_offset']), (1, 1, 0x754))
        records = resolve_graph_records(self.data, detail['blob_offset'], detail['count'])
        self.assertEqual([(r['group'], r['member'], r['candidate']) for r in records],
                         [(3, 259, 'CHR/CHR_0518.png')])
        self.assertEqual(records[0]['raw_hex'], '04 ff ff 01 03 31 00 00 57 00 d1 fe')

    def test_special_number_has_no_candidate(self):
        records = resolve_graph_records(self.data, 0x760, 1)
        self.assertEqual((records[0]['member'], records[0]['candidate']), (0xFFF, None))

    def test_zero_records_and_wrong_length_are_rejected(self):
        for raw in ('3300010054070000', '33010100540700', '12030000'):
            with self.assertRaises(UnsupportedCommand):
                parse_graph_disp(bytes.fromhex(raw))
        with self.assertRaises(UnsupportedCommand):
            resolve_graph_records(b'', 0x754, 1)

    def test_record_offsets_follow_the_existing_candidate_table(self):
        # 既有 数据/画面资源候选.tsv 用 address+index*12 的升序；单条记录时两者一致。
        with (BASE / '数据/画面资源候选.tsv').open(encoding='utf-8-sig', newline='') as f:
            rows = [r for r in csv.DictReader(f, delimiter='\t')
                    if r['剧本'] == 'MAC_000.bin' and r['命令偏移'] in ('0x0000D4', '0x000138')]
        detail = {r['命令偏移']: r for r in rows}
        record = resolve_graph_records(self.data, 0x754, 1)[0]
        self.assertEqual(f'0x{record["record_offset"]:06X}', detail['0x0000D4']['记录偏移'])
        self.assertEqual(record['candidate'], detail['0x0000D4']['候选图片（相对输出-保护边修复）'])
        bg = resolve_graph_records(self.data, 0x76C, 1)[0]
        self.assertEqual(bg['candidate'], detail['0x000138']['候选图片（相对输出-保护边修复）'])


class RealScriptStateTests(unittest.TestCase):
    def test_opening_crosses_msg_mode_and_stops_at_ext_goto(self):
        commands = commands_of('MAC_000.bin')
        rows = rows_for('MAC_000.bin')
        lines, _, pacing, conditions, writes, displays, _, stop, reads, sounds, fades, _ = convert_program(
            commands, rows, 0x88, voices_of(rows),
            data=(BASE.parent / '输出-保护边修复/MAC/MAC_000.bin').read_bytes())
        self.assertEqual(len(lines), 74)
        self.assertEqual([c['offset'] for c in conditions], [0xAC, 0x4D0])
        self.assertEqual((conditions[0]['operator'], conditions[0]['lhs_value'],
                          conditions[0]['rhs_value'], conditions[0]['result']), ('!=', 0, 0, False))
        self.assertTrue(all(c['result'] is False for c in conditions))
        self.assertEqual([(w['offset'], w['operation'], w['before'], w['after']) for w in writes],
                         [(0xBC, 'assign', 0, 1), (0x108, 'assign', 1, 0),
                          (0x4E0, 'assign', 0, 1), (0x57C, 'assign', 1, 0),
                          (0x700, 'assign', 0, 0), (0x734, 'assign', 0, 0)])
        self.assertEqual([p['offset'] for p in pacing][:6], [0xA0, 0xA4, 0xA8, 0xC4, 0xC8, 0xCC])
        # 0x1EC 已由 v7.4 地址对应译文补齐；time_wait 生成等待后停在 ext_goto。
        self.assertEqual((stop['name'], stop['offset']), ('ext_goto', 0x73C))
        self.assertEqual(stop['reason'], '跨剧本跳转（需 --follow-goto 继续）')
        self.assertIn('伊织「能借着演戏去体验各种不同的人生，我觉得很开心」 -VOICE_00000.wav;', lines)
        self.assertIn('一贵「你说什么！？你明明已经有喜欢的女生了吧！」 -VOICE_00015.wav;', lines)
        self.assertIn('寺谷「呃啊啊啊——」 -VOICE_00016.wav;', lines)
        self.assertEqual([(d['offset'], d['name']) for d in displays[:12]],
                         [(0xD0, 'msg_mode'), (0xD4, 'graph_disp'), (0x100, 'graph_disp'),
                          (0x110, 'msg_mode'), (0x138, 'graph_disp'), (0x194, 'graph_disp'),
                          (0x1E4, 'graph_disp'), (0x244, 'graph_disp'), (0x274, 'graph_disp'),
                          (0x294, 'graph_disp'), (0x2C0, 'graph_disp'), (0x32C, 'graph_disp')])
        self.assertEqual(len(displays), 31)
        self.assertEqual([d['mode'] for d in displays if d['name'] == 'msg_mode'], [5, 6, 5, 6, 6])
        self.assertTrue(all(d['webgal']['mapped'] is False for d in displays))
        self.assertEqual([r['candidate'] for d in displays for r in d.get('records', [])][:10],
                         ['CHR/CHR_0518.png', None, 'BG/BG_0218.png',
                          'CHR/CHR_2778.png', 'CHR/CHR_2820.png', 'CHR/CHR_2904.png', None,
                          'CHR/CHR_2904.png', 'CHR/CHR_2778.png', 'CHR/CHR_2820.png'])
        self.assertEqual([(f['offset'], f['direction']) for f in fades if f['name'] == 'fade_start'][:4],
                         [(0x358, 'fade_out'), (0x374, 'fade_in'),
                          (0x398, 'fade_out'), (0x3B4, 'fade_in')])

    def test_opening_word_is_not_written_before_the_conditional(self):
        import struct
        commands = commands_of('MAC_000.bin')
        before = [c for c in commands if c['offset'] < 0xAC and c['opcode'] == 0x09]
        targets = {struct.unpack_from('<H', bytes.fromhex(c['raw_hex']), 2)[0] for c in before}
        self.assertNotIn(0x600E, targets)

    def test_real_branch_fragment_takes_state_dependent_paths(self):
        voices = {voice: f'VOICE_{voice:05}.wav' for voice in range(2859, 2873)}
        lines, _, _, conditions, writes, _, _, stop, _, _, _, _ = convert_program(
            commands_of('MAC_013.bin'), rows_for('MAC_013.bin'), 0x6294, voices,
            data=(BASE.parent / '输出-保护边修复/MAC/MAC_013.bin').read_bytes())
        self.assertEqual(len(lines), 23)
        self.assertEqual([c['offset'] for c in conditions], [0x62AC, 0x639C])
        self.assertTrue(all(c['result'] for c in conditions))
        self.assertEqual(conditions[0]['lhs']['kind'], 'bit')
        self.assertEqual((conditions[0]['lhs']['bank'], conditions[0]['lhs']['index']), (1, 26))
        self.assertEqual([(w['offset'], w['operation'], w['after']) for w in writes],
                         [(0x6598, 'assign', 0), (0x65A4, 'assign', 0)])
        self.assertEqual((stop['name'], stop['offset']), ('ext_goto', 0x65AC))

    def test_constant_condition_and_calc_writes(self):
        commands = commands_of('MAC_013.bin')
        rows = rows_for('MAC_013.bin')
        lines, _, _, conditions, writes, _, _, stop, _, _, _, waits = convert_program(
            commands, rows, 0x4C5C, voices_of(rows),
            data=(BASE.parent / '输出-保护边修复/MAC/MAC_013.bin').read_bytes())
        self.assertEqual(len(lines), 90)
        self.assertEqual(conditions[0]['operator'], '==')
        # time_wait 现在会前进；片段越过 3 个等待和 7 条状态写入，停在 sel_disp4。
        self.assertEqual([(w['offset'], w['operation'], w['after']) for w in writes],
                         [(0x4D70, 'add', 1), (0x4D78, 'sub', -1), (0x4E34, 'add', 1),
                          (0x4F00, 'assign', 1), (0x51A8, 'assign', 0),
                          (0x5438, 'assign', 1), (0x5490, 'assign', 0)])
        self.assertEqual([(w['offset'], w['frames']) for w in waits],
                         [(0x4EE4, 60), (0x5308, 120), (0x5314, 120)])
        self.assertEqual((stop['name'], stop['offset']), ('sel_disp4', 0x555C))


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import MAC_命令表提取 as common
        data = common.ELF.read_bytes()
        segs = 状态字证据.segments(data)
        cls.data, cls.segs = data, segs
        cls.dis = 状态字证据.Dis(data, segs)

    def test_state_block_is_cleared_by_memset(self):
        info = 状态字证据.vm_init_evidence(self.dis, self.data, self.segs)
        self.assertEqual(info['memset']['size'], '0xD38680')
        self.assertEqual(info['memset']['value'], 0)
        self.assertEqual(info['vm_init']['state_table']['entries'][0], '0x00114BB0')

    def test_if_and_calc_tables_match_the_handlers(self):
        if_info = 状态字证据.if_evidence(self.dis, self.data, self.segs)
        self.assertEqual(if_info['compare_table']['entries'][:3],
                         ['0x00118850', '0x00118860', '0x00118870'])
        calc = 状态字证据.calc_evidence(self.dis, self.data, self.segs)
        self.assertEqual([v['address'] for v in list(calc['supported_operations'].values())[:3]],
                         ['0x00118D58', '0x00118D70', '0x00118D80'])
        self.assertEqual([v['name'] for v in calc['supported_operations'].values()],
                         ['assign', 'add', 'sub', 'mul', 'div', 'mod', 'and', 'or',
                          'store_imm', 'add'])
        self.assertIn('18 28 30 02', calc['supported_operations']['3']['raw'])

    def test_generated_evidence_file_is_present(self):
        payload = json.loads((BASE / '数据/状态字ELF证据.json').read_text(encoding='utf-8'))
        self.assertEqual(payload['worked_example']['offset'], '0x0000AC')
        self.assertIn('state_init', payload)
        self.assertTrue(payload['unknowns'])

    def test_display_evidence_matches_display_module(self):
        payload = json.loads((BASE / '数据/画面指令ELF证据.json').read_text(encoding='utf-8'))
        self.assertEqual(sorted(payload['msg_mode']['modes'], key=int), ['5', '6'])
        for mode, geometry in payload['msg_mode']['modes'].items():
            for key in ('x', 'y', 'w', 'h', 'aux', 'lines'):
                self.assertEqual(geometry[key], mac_display.MSG_MODES[int(mode)][key])
        self.assertEqual(payload['graph_disp']['length'], 8)
        self.assertEqual(payload['graph_disp']['record']['bytes'], mac_display.GRAPH_RECORD_BYTES)
        self.assertTrue(payload['unknowns'])


if __name__ == '__main__':
    unittest.main()
