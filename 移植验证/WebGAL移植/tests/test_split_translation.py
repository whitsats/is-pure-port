import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 合并拆分译文 import merge_fragments


class SplitTranslationTests(unittest.TestCase):
    def setUp(self):
        self.original = 'あ・い%K%P'
        self.data = b'xxxx' + self.original.encode('cp932') + b'\0'
        self.fragments = {4: [('あ', '甲')], 8: [('い', '乙')]}

    def test_exact_original_bytes_addresses_and_middle_dot(self):
        result = merge_fragments(self.data, 4, self.original, self.fragments, [4, 8])
        self.assertEqual(result['chinese'], '甲乙')
        self.assertEqual([x['address'] for x in result['fragments']], ['0x000004', '0x000008'])

    def test_rejects_mismatched_original_or_ambiguous_fragments(self):
        self.assertIsNone(merge_fragments(self.data, 4, '別の文%K%P', self.fragments, [4, 8]))
        ambiguous = {4: [('あ', '甲'), ('あ', '另')], 8: [('い', '乙')]}
        self.assertIsNone(merge_fragments(self.data, 4, self.original, ambiguous, [4, 8]))
        wrong = {4: [('あ', '甲')], 8: [('う', '乙')]}
        self.assertIsNone(merge_fragments(self.data, 4, self.original, wrong, [4, 8]))

    def test_rejects_unaccounted_japanese_or_missing_end_marker(self):
        different = b'xxxx' + 'あ、い%K%P'.encode('cp932') + b'\0'
        self.assertIsNone(merge_fragments(different, 4, 'あ、い%K%P', self.fragments, [4, 8]))
        without_end = b'xxxx' + 'あ・い'.encode('cp932') + b'\0'
        self.assertIsNone(merge_fragments(without_end, 4, 'あ・い', self.fragments, [4, 8]))


if __name__ == '__main__':
    unittest.main()
