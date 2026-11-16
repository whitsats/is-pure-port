"""对真实条件字节及不同状态验证保守求值规则。"""
from pathlib import Path
import unittest

from MAC_条件求值 import State, evaluate_if, operand


class Conditions(unittest.TestCase):
    def test_original_three_way_selection(self):
        data = (Path(__file__).resolve().parent / "输出-保护边修复/MAC/MAC_001.bin").read_bytes()
        conditions = [data[p:p + 16] for p in (0x388C, 0x389C, 0x38AC)]
        targets = (0x38C4, 0x3C2C, 0x40B8)
        for choice in range(3):
            state = State(words={(1, 0): choice})
            outcomes = [evaluate_if(ins, state) for ins in conditions]
            self.assertEqual([taken for taken, _ in outcomes], [i == choice for i in range(3)])
            self.assertEqual(outcomes[choice][1], targets[choice])

    def test_register_bit_and_signed_immediate(self):
        s = State(words={(1, 16): -3}, bits={(1, 34): 1})
        self.assertEqual(operand(0x6010, s), -3)
        self.assertEqual(operand(0xA022, s), 1)
        self.assertEqual(operand(0xFFFF, s), -1)
        with self.assertRaises(KeyError):
            operand(0x6011, s)

    def test_unsupported_composite_condition_is_rejected(self):
        instruction = bytearray.fromhex("02 00 00 00 c4 38 00 00 00 60 00 00 00 00 00 00")
        instruction[13] = 1
        with self.assertRaises(NotImplementedError):
            evaluate_if(instruction, State(words={(1, 0): 0}))

    def test_supported_comparisons_and_unknown_state(self):
        instruction = bytearray.fromhex("02 00 00 00 c4 38 00 00 00 60 02 00 00 00 00 00")
        state = State(words={(1, 0): 2})
        for operator, expected in ((0, True), (1, False), (3, True), (4, False), (5, False)):
            instruction[12] = operator
            self.assertEqual(evaluate_if(instruction, state), (expected, 0x38C4))
        instruction[12] = 2
        with self.assertRaises(NotImplementedError):
            evaluate_if(instruction, state)
        instruction[12] = 0
        with self.assertRaises(KeyError):
            evaluate_if(instruction, State())


if __name__ == "__main__":
    unittest.main()
