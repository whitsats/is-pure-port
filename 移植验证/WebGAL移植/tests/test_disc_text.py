from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '转换器'))
from 校验实际汉化盘 import matches


class DiscTextTests(unittest.TestCase):
    def test_checks_bytes_and_ff_padding(self):
        table = {'中': ['8140', '8141'], '文': ['8142']}
        self.assertEqual(matches('中文A', bytes.fromhex('8141 8142 41 ff ff'), table), '逐字节一致')
        self.assertEqual(matches('中文A', bytes.fromhex('8141 8142 41 ff 00'), table), '不一致')
        self.assertEqual(matches('中甲', bytes.fromhex('8141 8142 ff'), table), '字码缺失')
        self.assertEqual(matches('', b'', table), '无译文')


if __name__ == '__main__':
    unittest.main()
