from pathlib import Path
import struct
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from emit_webgal import convert_program
from mac_state import State


def cmd(offset, op, raw):
    return {'offset': offset, 'opcode': op, 'name': {4: 'int_call', 5: 'int_return'}.get(op, 'stop'),
            'raw_hex': raw.hex()}


def call(offset, target):
    return cmd(offset, 4, bytes([4, 0, 0, 0]) + struct.pack('<I', target))


class InternalCallTests(unittest.TestCase):
    def test_nested_calls_return_in_order_and_restore_resource(self):
        commands = [call(0, 0x20), cmd(8, 0xFF, b'\xff\0\0\0'),
                    call(0x20, 0x40), cmd(0x28, 5, b'\x05\0\0\0'),
                    cmd(0x40, 5, b'\x05\0\0\0')]
        state = State()
        state.write_context_u32(0x52E0, 123)
        result = convert_program(commands, {}, 0, state=state)
        events, stop = result[6], result[7]
        self.assertEqual([e['name'] for e in events], ['int_call', 'int_call', 'int_return', 'int_return'])
        self.assertEqual([e['target'] for e in events], [0x20, 0x40, 0x28, 8])
        self.assertEqual([e['depth'] for e in events], [1, 2, 1, 0])
        self.assertEqual(state.read_context_u32(0x52E0), 123)
        self.assertEqual(stop['offset'], 8)

    def test_empty_return_and_bad_call_target_stop_explicitly(self):
        result = convert_program([cmd(0, 5, b'\x05\0\0\0')], {}, 0)
        self.assertIn('没有对应', result[7]['reason'])
        result = convert_program([call(0, 0x10), cmd(8, 0xFF, b'\xff\0\0\0')], {}, 0)
        self.assertIn('命令边界', result[7]['reason'])

    def test_cross_script_jump_with_live_call_stack_is_rejected(self):
        commands = [call(0, 0x20), cmd(8, 0xFF, b'\xff\0\0\0'),
                    cmd(0x20, 6, b'\x06\0\x02\0')]
        result = convert_program(commands, {}, 0)
        self.assertIn('调用栈未清空', result[7]['reason'])

    def test_optional_byte_output_preserves_word_bit_aliasing(self):
        commands = [cmd(0, 9, bytes.fromhex('090010a001000000')),
                    cmd(8, 9, bytes.fromhex('090e016102000000')),
                    cmd(16, 0xFF, b'\xff\0\0\0')]
        result = convert_program(commands, {}, 0, emit_state_bytes=True)
        self.assertEqual(result[0], ['setVar:mac_b_00422=1;',
                                     'setVar:mac_b_00422=2;', 'setVar:mac_b_00423=0;'])

    def test_quick_save_simplification_is_explicit_and_parameter_limited(self):
        commands = [cmd(0, 0x5A, bytes.fromhex('5a020000')),
                    cmd(4, 0xFF, b'\xff\0\0\0')]
        self.assertEqual(convert_program(commands, {}, 0)[7]['offset'], 0)
        result = convert_program(commands, {}, 0, prototype_save=True)
        self.assertEqual(result[7]['offset'], 4)
        self.assertEqual(result[4][0]['operation'], 'prototype_save_omitted')
        unsupported = [cmd(0, 0x5A, bytes.fromhex('5a010000'))]
        self.assertIn('尚未核查', convert_program(unsupported, {}, 0, prototype_save=True)[7]['reason'])

    def test_title_simplification_is_explicit_and_parameter_limited(self):
        commands = [cmd(0, 0x50, bytes.fromhex('50000000')),
                    cmd(4, 0xFF, b'\xff\0\0\0')]
        self.assertEqual(convert_program(commands, {}, 0)[7]['offset'], 0)
        result = convert_program(commands, {}, 0, prototype_title=True)
        self.assertEqual(result[7]['offset'], 4)
        self.assertFalse(result[5][0]['webgal']['mapped'])
        unsupported = [cmd(0, 0x50, bytes.fromhex('50010000'))]
        self.assertIn('尚未核查', convert_program(unsupported, {}, 0, prototype_title=True)[7]['reason'])


if __name__ == '__main__':
    unittest.main()
