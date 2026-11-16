"""0x1EC 文本槽与“字码缺失”的核查。

这一组用例把调查结论钉住：汉化盘该槽写的就是 v7.4 译文，唯一障碍是作者码表里没有 '—' 的字码。
如果哪天码表或归档变了，这些断言会先失败，而不是让转换器悄悄换一份文本。
"""
import csv
import json
from pathlib import Path
import sys
import unittest

BASE = Path(__file__).resolve().parents[1]          # 移植验证/WebGAL移植
PROJECT = BASE.parent                               # 移植验证
sys.path.insert(0, str(PROJECT))
from 本地路径 import ZH_ROOT

IS_ROOT = ZH_ROOT
sys.path.insert(0, str(BASE / '转换器'))
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(IS_ROOT / '打盘'))
import MAC_解析 as mac                              # noqa: E402
import 烘焙文本 as bake                              # noqa: E402
from emit_webgal import convert_program, normalize_mapping_row  # noqa: E402

ARCHIVE = IS_ROOT / '一键打盘/patch/mac-v6.afs'
ORIGINAL_ISO = IS_ROOT / '素材/PS2原盘/game-original.iso'
V74_ISO = IS_ROOT / '成品/PS2汉化-v7.4/game-v7.4.iso'
TEXT_OFFSET = 0x0C2B
JAPANESE = '寺谷「オオオッ、イヤがっていたわりにはノリノリじゃねえーか」'
V74_TEXT = '寺谷「噢噢噢——嘴上说着不情愿，拍起来这不是挺放得开的嘛！」'


def script_from_archive(archive_bytes, index=0):
    return bytes(mac.script(archive_bytes, mac.entries(archive_bytes)[index]))


def load_archive():
    return ARCHIVE.read_bytes()


class DiscSlotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slot = script_from_archive(load_archive())[TEXT_OFFSET:TEXT_OFFSET + len(JAPANESE.encode('cp932'))]
        cls.table = bake.load_author_table(bake.AUTHOR_TABLE)

    def test_original_disc_holds_the_japanese_line(self):
        original = script_from_archive(mac.load(ORIGINAL_ISO))
        slot = original[TEXT_OFFSET:TEXT_OFFSET + len(JAPANESE.encode('cp932'))]
        self.assertEqual(slot.decode('cp932'), JAPANESE)

    def test_patched_archive_and_v74_iso_agree(self):
        v74 = script_from_archive(mac.load(V74_ISO))
        self.assertEqual(script_from_archive(load_archive()), v74)

    def test_slot_bytes_are_the_v74_translation(self):
        # 60 字节 = 30 个双字节字；'—' 落在作者码表缺失的 0x9643 上。
        self.assertEqual(len(self.slot), 60)
        decoded, index, chars = [], 0, []
        reverse = {int(code, 16): ch for ch, codes in self.table.items() for code in codes}
        while index < len(self.slot):
            code = (self.slot[index] << 8) | self.slot[index + 1]
            decoded.append(reverse.get(code, f'<{code:04X}>'))
            chars.append(f'{code:04X}')
            index += 2
        self.assertEqual(''.join(decoded), V74_TEXT.replace('—', '<9643>'))
        self.assertEqual(chars.count('9643'), 2)
        self.assertEqual(len(V74_TEXT), 30)

    def test_author_table_lacks_the_dash(self):
        self.assertIn('、', self.table)
        self.assertNotIn('—', self.table)

    def test_supplementary_codes_are_supported_and_unambiguous(self):
        payload = json.loads((BASE / '数据/字码补充推断.json').read_text(encoding='utf-8'))
        codes = payload['codes']
        self.assertEqual(codes['0x9643']['char'], '—')
        self.assertGreaterEqual(codes['0x9643']['support'], 100)
        self.assertEqual(codes['0x8140']['char'], '\u3000')
        self.assertEqual(payload['excluded'], {})
        self.assertIn('字体字模未核对', payload['status'])


class ExtendedMappingTests(unittest.TestCase):
    def test_extended_table_marks_the_line_as_verified(self):
        path = BASE / '数据/三版译文与汉化盘核查_补字码.tsv'
        with path.open(encoding='utf-8-sig', newline='') as f:
            row = next(r for r in csv.DictReader(f, delimiter='\t')
                       if r['剧本'] == 'MAC_000.bin' and r['指令偏移'] == '0x0001EC')
        self.assertEqual(row['v7.4工程文本对盘'], '逐字节一致')
        self.assertEqual(row['v7.4工程中文'], V74_TEXT)

    def test_opening_reaches_time_wait_with_extended_table(self):
        with (BASE / '数据/三版译文与汉化盘核查_补字码.tsv').open(encoding='utf-8-sig', newline='') as f:
            rows = {int(r['指令偏移'], 16): normalize_mapping_row(r)
                    for r in csv.DictReader(f, delimiter='\t') if r['剧本'] == 'MAC_000.bin'}
        data = json.loads((BASE / '数据/入口片段.json').read_text(encoding='utf-8'))['scripts']
        commands = next(s for s in data if s['file'] == 'MAC_000.bin')['commands']
        voices = {int(r['语音号']): f'VOICE_{int(r["语音号"]):05}.wav'
                  for r in rows.values() if r['语音号'] not in ('-1', '')}
        lines, sources, _, _, _, _, _, stop, _, _, _, _ = convert_program(
            commands, rows, 0x88, voices,
            data=(PROJECT / '输出-保护边修复/MAC/MAC_000.bin').read_bytes())
        self.assertEqual(len(lines), 74)
        # file_read/file_wait、SE、fade 与 time_wait 都已实现，现停在 ext_goto。
        self.assertEqual((stop['name'], stop['offset'], stop['raw_hex']),
                         ('ext_goto', 0x73C, '06000100'))
        self.assertEqual(sources[-1]['offset'], 0x6C8)
        # 0x1EC 之后接 0x1F8、0x204、0x210，再跳到 0x238。
        self.assertEqual([s['offset'] for s in sources[19:23]], [0x1EC, 0x1F8, 0x204, 0x210])
        self.assertIn('噢噢噢——嘴上说着不情愿', lines[19])
        self.assertEqual(sources[22]['offset'], 0x210)
        self.assertEqual(sources[23]['offset'], 0x238)
        self.assertIn('回过神来时', lines[23])


if __name__ == '__main__':
    unittest.main()
