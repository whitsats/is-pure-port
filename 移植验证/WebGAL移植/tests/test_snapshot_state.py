from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_progress_snapshot import (EeMemory, EE_SIZE, SCENE_TABLE_COUNT, SCENE_TABLE_PTR,
                                   STORY_COUNT, VISITED_BITS)
from mac_state import State, UnsupportedCommand, apply_reg_calc
from mac_state_snapshot import SnapshotState


class SnapshotStateTests(unittest.TestCase):
    def setUp(self):
        memory = EeMemory(bytearray(EE_SIZE))
        self.gp, self.base = 0x2779F0, 0xD72980
        memory.write32(self.gp - 0x6D44, self.base)
        memory.write32(STORY_COUNT, 2)
        memory.write32(SCENE_TABLE_PTR, 0xA58A8C)
        memory.write32(SCENE_TABLE_COUNT, 1)
        memory.write16(0xA58A8C + 8, 3)
        memory.set_bit(VISITED_BITS, 0)
        self.state = SnapshotState(memory, self.gp, 'synthetic')

    def test_state_words_and_bits_share_actual_memory(self):
        self.state.memory.write16(self.base + 0x220, 0xFFFE)
        self.assertEqual(self.state.read(0x6000), -2)
        self.state.write(0x6000, 42)
        self.assertEqual(self.state.memory.u16(self.base + 0x220), 42)
        self.state.memory.set_bit(self.base + 0x420, 26)
        self.assertEqual(self.state.read(0xA01A), 1)

    def test_reg17_opt_in_updates_shared_memory(self):
        result = apply_reg_calc(bytes.fromhex('0917010000000000'), self.state)
        self.assertEqual(result['operation'], 'reg_calc_17_snapshot')
        self.assertTrue(result['all_set'])
        self.assertEqual(self.state.memory.u16(self.base + 0x440), 1)
        self.assertEqual(self.state.memory.u32(self.base + 0x4B0), 0)
        self.assertEqual(self.state.read(0x6110), 1)
        self.assertEqual(result['scene_flag_indices_set'], [0])

    def test_default_state_still_refuses_reg17(self):
        with self.assertRaises(UnsupportedCommand):
            apply_reg_calc(bytes.fromhex('0917010000000000'), State())


if __name__ == '__main__':
    unittest.main()
