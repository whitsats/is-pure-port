from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_progress_snapshot import EeMemory, EE_SIZE, SnapshotError
from mac_title_snapshot import (TITLE_RECORD_COUNT, TITLE_TABLE_COUNT_CANDIDATE,
                                TITLE_TABLE_PTR, decode_title, inspect_title)


class TitleSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.memory = EeMemory(bytearray(EE_SIZE))
        self.gp, self.state, self.table = 0x2779F0, 0xD72980, 0xA551E8
        self.memory.write32(self.gp - 0x6D44, self.state)
        self.memory.write32(TITLE_TABLE_PTR, self.table)
        self.memory.write32(TITLE_TABLE_COUNT_CANDIDATE, 2)
        self.memory.write16(self.state + 0x440, 1)
        self.memory.write32(self.state + 0x4B0, 1)
        self.memory.write32(self.table + 12, 0xA60000)
        self.memory.write32(self.table + 16, 0xA60100)
        self.memory.data[0xA60000:0xA60006] = b'First\0'
        self.memory.data[0xA60100:0xA60106] = b'Title\0'

    def test_record_selection_and_display_parameter(self):
        result = inspect_title(self.memory, self.gp, {})
        self.assertEqual((result['first_string'], result['title']), ('First', 'Title'))
        self.assertEqual(result['display_parameter'], 7)

    def test_missing_pointer_and_out_of_range_are_rejected(self):
        self.memory.write32(self.table + 16, 0)
        with self.assertRaises(SnapshotError):
            inspect_title(self.memory, self.gp, {})
        self.memory.write16(self.state + 0x440, TITLE_RECORD_COUNT)
        with self.assertRaises(SnapshotError):
            inspect_title(self.memory, self.gp, {})

    def test_adjacent_52_is_not_used_as_the_record_limit(self):
        # 第 56 项仍是合法记录；旧的 0xB1EC18=52 上限会错误拒绝它。
        self.memory.write32(TITLE_TABLE_COUNT_CANDIDATE, 52)
        self.memory.write16(self.state + 0x440, 56)
        record = self.table + 12 * 56
        self.memory.write32(record, 0xA60200)
        self.memory.write32(record + 4, 0xA60300)
        self.memory.data[0xA60200:0xA60206] = b'Last\0\0'
        self.memory.data[0xA60300:0xA60306] = b'Final\0'
        result = inspect_title(self.memory, self.gp, {})
        self.assertEqual(result['title'], 'Final')
        self.assertEqual(result['adjacent_count_candidate'], 52)
        self.assertEqual(result['title_record_count'], 57)

    def test_unknown_codes_are_visible_and_not_guessed(self):
        self.assertEqual(decode_title(b'A\x81\x45', {}), ('A<8145>', ['8145']))
        with self.assertRaises(SnapshotError):
            decode_title(b'\x81', {})


if __name__ == '__main__':
    unittest.main()
