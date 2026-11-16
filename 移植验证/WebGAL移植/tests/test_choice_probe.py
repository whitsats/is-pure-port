import json
from pathlib import Path
import struct
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from mac_reader import ROOT, load_table
from 生成选项核查场景 import build_choice


class ChoiceProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (ROOT / '输出-保护边修复/MAC/MAC_001.bin').read_bytes()
        cls.info = json.loads((ROOT / 'MAC_命令表/脚本验证.json').read_text(encoding='utf-8'))['MAC_001.bin']
        cls.table = load_table()

    def test_original_choice_destinations(self):
        text, records = build_choice(self.data, self.info['boundary'], self.info['text_start'], 0x3878, self.table)
        self.assertEqual([x[2] for x in records], [0x38C4, 0x3C2C, 0x40B8])
        self.assertIn('謝る:choice_0', text)
        self.assertIn('0x0040B8', text)

    def test_state_dependent_option_rejected(self):
        data = bytearray(self.data)
        table = struct.unpack_from('<I', data, 0x3878 + 4)[0]
        struct.pack_into('<H', data, table + 8, 0x6010)
        with self.assertRaisesRegex(ValueError, '依赖状态'):
            build_choice(data, self.info['boundary'], self.info['text_start'], 0x3878, self.table)

    def test_chinese_requires_exact_original(self):
        originals = ['謝る', 'ふざけろ！', '…………']
        chinese = ['道歉', '少扯了！', '…………']
        translations = {i: {'匹配状态': '唯一匹配', '日文原文': original, '汉化包中文': text}
                        for i, (original, text) in enumerate(zip(originals, chinese))}
        scene, _ = build_choice(self.data, self.info['boundary'], self.info['text_start'], 0x3878, self.table, translations)
        self.assertIn('道歉:choice_0|少扯了！:choice_1|…………:choice_2', scene)
        translations[1]['日文原文'] = '不符'
        with self.assertRaisesRegex(ValueError, '没有严格匹配'):
            build_choice(self.data, self.info['boundary'], self.info['text_start'], 0x3878, self.table, translations)


if __name__ == '__main__':
    unittest.main()
