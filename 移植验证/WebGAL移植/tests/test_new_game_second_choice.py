import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 验证新游戏第二选项 import analyze


class SecondChoiceTests(unittest.TestCase):
    def test_all_opening_combinations_reach_next_choice(self):
        report = analyze()
        self.assertEqual([x['first_choice'] for x in report['branches']], [0, 1, 2])
        for first in report['branches']:
            self.assertEqual(first['second_choice']['visible_indices'], [0, 1, 2, 3])
            self.assertEqual([p['dialogues'] for p in first['paths']], [433, 416, 421, 429])
            for second, path in enumerate(first['paths']):
                self.assertEqual(path['choice'], second)
                self.assertEqual((path['stop']['script'], path['stop']['offset'], path['stop']['name']),
                                 ('MAC_003.bin', 0x24C4, 'sel_disp4'))
                self.assertEqual(path['state_bytes_at_stop']['0022E'], second)


if __name__ == '__main__':
    unittest.main()
