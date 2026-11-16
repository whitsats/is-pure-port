import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_display import apply_graph_prio
from mac_state import State, UnsupportedCommand
from emit_webgal import convert_program
import mac_reader  # 将项目根目录加入模块搜索路径
import MAC_命令表提取 as common
import 状态字证据 as evidence


class GraphPrioTests(unittest.TestCase):
    def test_handler_reads_layer_and_unsigned_priority_then_advances_four(self):
        elf = common.ELF.read_bytes()
        table = common.load_table(elf)
        self.assertEqual((table[0x2E]['bytes'], table[0x2E]['handler']), (4, 0x11C900))
        dis = evidence.Dis(elf, evidence.segments(elf))
        handler = {x['at']: f"{x['mnemonic']} {x['op']}" for x in dis.read(0x11C900, 0x3C)}
        self.assertEqual(handler['0x0011C918'], 'lhu $a1, 2($v1)')
        self.assertEqual(handler['0x0011C91C'], 'jal 0x12b1c8')
        self.assertEqual(handler['0x0011C920'], 'lbu $a0, 1($v1)')
        self.assertEqual(handler['0x0011C930'], 'addiu $v0, $v0, 4')
        callee = {x['at']: f"{x['mnemonic']} {x['op']}" for x in dis.read(0x12B1C8, 0x38)}
        self.assertEqual(callee['0x0012B1C8'], 'slti $v1, $a1, 0xa')
        self.assertEqual(callee['0x0012B1FC'], 'sb $a1, -0x2103($at)')

    def test_priority_clamp_and_slot_stride(self):
        state = State()
        detail = apply_graph_prio(bytes.fromhex('2e010100'), state)
        self.assertEqual((detail['layer'], detail['priority'], detail['state_offset']), (1, 1, '0x3E005'))
        self.assertEqual(state.memory_bytes[0x3E005], 1)
        detail = apply_graph_prio(bytes.fromhex('2e02ffff'), state)
        self.assertEqual(detail['priority'], 9)
        self.assertEqual(state.memory_bytes[0x3E10D], 9)
        with self.assertRaises(UnsupportedCommand):
            apply_graph_prio(bytes.fromhex('2e00'), state)

    def test_conversion_records_state_and_continues(self):
        commands = [{'offset': 0, 'opcode': 0x2E, 'name': 'graph_prio', 'raw_hex': '2e010100'},
                    {'offset': 4, 'opcode': 0xFF, 'name': 'unknown', 'raw_hex': 'ff000000'}]
        state = State()
        result = convert_program(commands, {}, 0, state=state)
        self.assertEqual(result[7]['offset'], 4)
        self.assertEqual(result[5][0]['priority'], 1)
        self.assertEqual(state.memory_bytes[0x3E005], 1)


if __name__ == '__main__':
    unittest.main()
