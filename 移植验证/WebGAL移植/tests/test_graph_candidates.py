from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '转换器'))
from 提取画面资源候选 import candidate


class GraphCandidateTests(unittest.TestCase):
    def test_resource_groups_and_sentinel(self):
        self.assertEqual(candidate(0x2000)[2], 'EV/EV_0000.png')
        self.assertEqual(candidate(0x106D)[2], 'BG/BG_0218.png')
        self.assertEqual(candidate(0x3003)[2], 'CHR/CHR_0006.png')
        self.assertEqual(candidate(0x3FFF)[2], None)
        self.assertEqual(candidate(0x5001)[3], '资源组未确认')


if __name__ == '__main__':
    unittest.main()
