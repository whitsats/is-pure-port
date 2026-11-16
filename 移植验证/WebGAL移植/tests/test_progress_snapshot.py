from pathlib import Path
import struct
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_progress_snapshot import (EeMemory, EE_SIZE, SCENE_FLAGS, SCENE_TABLE_COUNT,
                                   SCENE_TABLE_PTR, STORY_COUNT, VISITED_BITS,
                                   SnapshotError, simulate_reg17)


class ProgressSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.memory = EeMemory(bytearray(EE_SIZE))
        self.gp, self.state, self.scene_table = 0x2779F0, 0xD72980, 0xA58A8C
        self.memory.write32(self.gp - 0x6D44, self.state)
        self.memory.write32(SCENE_TABLE_PTR, self.scene_table)
        self.memory.write32(SCENE_TABLE_COUNT, 2)
        self.memory.write16(self.scene_table + 8, 3)
        self.memory.write16(self.scene_table + 20, 2)

    def test_incomplete_does_not_set_scene_flags(self):
        self.memory.write32(STORY_COUNT, 3)
        self.memory.set_bit(VISITED_BITS, 0)
        result = simulate_reg17(self.memory, self.gp, 0)
        self.assertEqual(result['previous_bit'], 1)
        self.assertFalse(result['all_set'])
        self.assertEqual(self.memory.u32(self.state + 0x4B0), 1)
        self.assertEqual(self.memory.u8(SCENE_FLAGS), 0)

    def test_last_bit_triggers_only_type_three(self):
        self.memory.write32(STORY_COUNT, 2)
        self.memory.set_bit(VISITED_BITS, 0)
        result = simulate_reg17(self.memory, self.gp, 1)
        self.assertEqual(result['previous_bit'], 0)
        self.assertEqual(self.memory.u16(self.state + 0x440), 1)
        self.assertEqual(self.memory.u32(self.state + 0x4B0), 0)
        self.assertEqual(result['scene_flag_indices_set'], [0])
        self.assertEqual(self.memory.u8(SCENE_FLAGS), 1)

    def test_zero_count_takes_all_complete_path(self):
        self.memory.write32(STORY_COUNT, 0)
        result = simulate_reg17(self.memory, self.gp, 3)
        self.assertTrue(result['all_set'])
        self.assertEqual(result['scene_flag_indices_set'], [0])

    def test_invalid_pointer_does_not_partially_write(self):
        self.memory.write32(STORY_COUNT, 1)
        self.memory.write32(SCENE_TABLE_PTR, 0x1FFFFFE)
        old = self.memory.u8(VISITED_BITS)
        with self.assertRaises(SnapshotError):
            simulate_reg17(self.memory, self.gp, 0)
        self.assertEqual(self.memory.u8(VISITED_BITS), old)
        self.assertEqual(self.memory.u16(self.state + 0x440), 0)


if __name__ == '__main__':
    unittest.main()
