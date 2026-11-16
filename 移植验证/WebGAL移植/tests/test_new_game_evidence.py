import json
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
EVIDENCE = BASE / '数据/新游戏0x17证据.json'


class NewGameEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))

    def test_state_block_and_bss_are_from_elf(self):
        self.assertEqual(self.evidence['items']['state_block']['status'], 'code_evidence')
        self.assertEqual(self.evidence['items']['state_block']['size'], '0x0D38680')
        self.assertEqual(self.evidence['bss']['section_type'], 'SHT_NOBITS')
        self.assertEqual(self.evidence['bss']['addresses']['story_count'], '0xB1EC20')

    def test_story_count_is_explicitly_static_derivation(self):
        item = self.evidence['items']['story_count']
        self.assertEqual(item['status'], 'static_derivation')
        self.assertEqual(item['value'], 57)
        self.assertIn('未取得', item['runtime_write_point'])
        self.assertEqual(item['static_direct_store_hits'], [])
        self.assertEqual(self.evidence['title_table']['record_count'], 57)
        self.assertEqual(self.evidence['title_table']['last_record_offset'], '0x000D88')
        self.assertEqual(self.evidence['title_table']['next_record_offset'], '0x000D94')

    def test_count_reads_and_handlers_match_original_instructions(self):
        reads = [item['address'] for item in self.evidence['items']['story_count']['reads']]
        self.assertEqual(reads, ['0x00117204', '0x001172AC'])
        self.assertEqual(self.evidence['items']['reg17']['address'], '0x00118FD0')
        self.assertEqual(self.evidence['items']['vib_set']['address'], '0x0011EF80')
        self.assertEqual(self.evidence['items']['vib_set']['state_offsets'],
                         ['G+0x299..G+0x29D'])
        self.assertEqual(self.evidence['items']['quick_save']['status'], 'unknown')
        self.assertIn('未实现', self.evidence['items']['quick_save']['note'])


if __name__ == '__main__':
    unittest.main()
