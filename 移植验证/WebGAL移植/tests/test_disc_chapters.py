"""批量接入：从 MAC_007:0x4314 起的整条主线必须一次编译、目标与语音齐全。"""
import json
import re
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
SAMPLE = BASE / '新游戏打盘版'
SCENE = SAMPLE / 'public/game/scene'
REPORT = BASE / '数据/批量章节扫描_写入2.json'


class BatchChapters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(REPORT.read_text(encoding='utf-8'))
        cls.scenes = {site: info for chapter in cls.report['chapters']
                      for site, info in chapter['scenes'].items()}

    def test_covers_every_script_up_to_the_final_end(self):
        self.assertEqual(len(self.report['chapters']), 49)
        self.assertEqual(self.report['scene_count'], 177)
        self.assertEqual(self.report['missing_voices'], [])
        self.assertEqual(self.report['failures'], [])
        chapters = {chapter['site'].split(':')[0] for chapter in self.report['chapters']}
        self.assertIn('MAC_008', chapters)
        self.assertIn('MAC_056', chapters)

    def test_every_scene_and_jump_target_exists(self):
        for site, info in self.scenes.items():
            path = SCENE / info['scene']
            self.assertTrue(path.is_file(), site)
        missing = []
        for path in SCENE.glob('mac_*.txt'):
            for line in path.read_text(encoding='utf-8').splitlines():
                if not line.startswith('changeScene:'):
                    continue
                target = line.split(':', 1)[1].rstrip(';').split(' ')[0]
                if not (SCENE / target).is_file():
                    missing.append((path.name, target))
        self.assertEqual(missing, [])

    def test_voice_references_have_audio(self):
        voices = {name for path in SCENE.glob('mac_*.txt')
                  for name in re.findall(r'-(VOICE_\d{5}\.wav)', path.read_text(encoding='utf-8'))}
        missing = sorted(name for name in voices if not (SAMPLE / 'public/game/vocal' / name).is_file())
        self.assertEqual(missing, [])

    def test_seven_endings_share_the_final_instruction(self):
        stops = [info['stop'] for info in self.scenes.values()
                 if info['stop'] and info['stop']['name'] == 'end']
        self.assertEqual(len(stops), 7)
        self.assertEqual({(stop['script'], stop['offset'], stop['raw_hex']) for stop in stops},
                         {('MAC_056.bin', 0x2D88, '01010000')})

    def test_no_scene_still_ends_at_the_old_mac010_cut(self):
        offenders = [path.name for path in SCENE.glob('mac_010_*.txt')
                     if '本版边界：MAC_010.bin 0xB98' in path.read_text(encoding='utf-8')]
        self.assertEqual(offenders, [])

    def test_untranslated_lines_are_recorded_not_invented(self):
        records = [record for info in self.scenes.values() for record in info['ignored']
                   if record['category'] in ('untranslated_japanese', 'control_code_line')]
        self.assertTrue(records)
        japanese = [record for record in records if record['category'] == 'untranslated_japanese']
        self.assertTrue(all(record['raw_text'] and not record['text'].count(';') for record in japanese))

    def test_chapter_scenes_open_with_the_static_title(self):
        titles = {record['index']: record['title'] for record in
                  json.loads((BASE / '数据/章节标题静态表.json').read_text(encoding='utf-8'))['records']}
        checked = 0
        for chapter in self.report['chapters']:
            script = int(chapter['site'].split(':')[0].split('_')[1])
            info = chapter['scenes'].get(chapter['site'])
            if not info:
                continue
            lines = (SCENE / info['scene']).read_text(encoding='utf-8').splitlines()
            intro = next((line for line in lines if line.startswith('intro:')), None)
            if intro is None:
                continue   # 收尾剧本从 0x158 等入口开始，不重发章节标题
            self.assertEqual(intro, f'intro:{titles[script]};', chapter['site'])
            checked += 1
        self.assertGreaterEqual(checked, 45)

    def test_effect_families_are_registered_from_disc_bytes(self):
        from mac_effect import CHANNEL_POLL, CHANNEL_STOP, EXTRA_STARTS, SCREEN_START
        self.assertEqual(len(SCREEN_START), 40)
        self.assertTrue(all(len(raw) == 40 for raw in EXTRA_STARTS))
        self.assertEqual(set(CHANNEL_POLL), {bytes.fromhex('6b00fd'), bytes.fromhex('6b02fd')})
        self.assertEqual(set(CHANNEL_STOP), {bytes.fromhex('6b00fc'), bytes.fromhex('6b02fc')})


if __name__ == '__main__':
    unittest.main()
