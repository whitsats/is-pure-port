import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 隔离核查effect_start import inspect, RAW, WAIT_RAW
from 核对岸边告白演出 import inspect as inspect_chapter_effects


class EffectIsolatedTests(unittest.TestCase):
    snapshot = BASE.parent.parent / '_archive/PCSX2测试/PCSX2_newgame_isolation/emulator/sstates/SLPM-66570 (7C3CD179).45.p2s'

    def test_real_instruction_pair_in_isolated_snapshot(self):
        original = (BASE.parent / '输出-保护边修复/MAC/MAC_004.bin').read_bytes()
        self.assertEqual(original[0x1AA8:0x1AA8 + len(RAW)], RAW)
        self.assertEqual(original[0x1C84:0x1C84 + len(WAIT_RAW)], WAIT_RAW)
        self.assertEqual(original[0x21F4:0x21F4 + len(WAIT_RAW)], WAIT_RAW)
        result = inspect(self.snapshot, completion=True)
        self.assertEqual(result['ip_advance'], 40)
        self.assertEqual(result['calls']['0x00131620'], 1)
        self.assertEqual(result['calls']['0x001316B8'], 1)
        self.assertEqual(result['effect_wait']['ip_advance'], 8)
        self.assertEqual(result['effect_wait']['calls']['0x001317F0'], 1)
        self.assertIn('0x3F198', {x['offset'] for x in result['effect_wait']['changed_state_ranges']})
        rows = result['completion_probe']['rows']
        self.assertEqual([row['request']['advance'] for row in rows], [8, 8, 8, 8])
        self.assertEqual([row['first_poll']['advance'] for row in rows], [0, 0, 0, 0])
        self.assertEqual([row['busy_poll']['advance'] for row in rows], [0, 0, 0, 0])
        self.assertEqual([row['poll_after_callback']['advance'] for row in rows], [8, 8, 0, 8])

    def test_type_three_release_waits_eight_ticks_and_palette_advances(self):
        result = inspect_chapter_effects(self.snapshot)
        self.assertEqual((result['start_advance'], result['request_advance'], result['first_poll_advance']),
                         (40, 8, 0))
        self.assertEqual(result['rise'][-1], 1024)
        self.assertEqual([frame['advance'] for frame in result['completion_frames']], [0] * 7 + [8])
        self.assertEqual([frame['busy'] for frame in result['completion_frames']], [1] * 7 + [0])
        self.assertEqual([(row['slot'], row['advance'], row['value']) for row in result['palettes']],
                         [(slot, 4, 13) for slot in (1, 2, 3)])


if __name__ == '__main__':
    unittest.main()
