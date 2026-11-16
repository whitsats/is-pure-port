"""三条数值条在生成场景中的接线回归。"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / '新游戏打盘高清版/public/game/scene'


def lines(name):
    return (SCENE / name).read_text(encoding='utf-8').splitlines()


class NumericBars(unittest.TestCase):
    def test_initial_values_are_written_in_entry_scene(self):
        scene = lines('mac_000_0x00000c.txt')
        for variable in ('mac_6026', 'mac_602a', 'mac_602b', 'mac_602c'):
            self.assertIn(f'setVar:{variable}=20 -next;', scene[:4])

    def test_first_choice_applies_original_deltas(self):
        apology = '\n'.join(lines('mac_001_0x0038c4.txt')[:110])
        self.assertIn('setVar:mac_6026=mac_6026+(1) -next;', apology)
        self.assertIn('setVar:mac_602a=mac_602a+(1) -next;', apology)
        self.assertNotIn('setVar:mac_602b=mac_602b+(1) -next;', apology)
        self.assertNotIn('setVar:mac_602c=mac_602c+(1) -next;', apology)

        joke = '\n'.join(lines('mac_001_0x003c2c.txt')[:110])
        self.assertIn('setVar:mac_602b=mac_602b+(1) -next;', joke)
        self.assertIn('setVar:mac_602c=mac_602c+(1) -next;', joke)
        self.assertNotIn('setVar:mac_6026=mac_6026+(1) -next;', joke)
        self.assertNotIn('setVar:mac_602a=mac_602a+(1) -next;', joke)

    def test_third_choice_threshold_reads_602c(self):
        scene = lines('mac_003_0x00000c.txt')
        choice = next(index for index, line in enumerate(scene) if line.startswith('choose:') and '青梅竹马而已' in line)
        self.assertIn('jumpLabel:mac_24c4 -when=mac_602c<21;', scene[choice - 4:choice])

    def test_signed_wrap_guards_are_emitted(self):
        scene = '\n'.join(lines('mac_001_0x003c2c.txt'))
        for variable in ('mac_602b', 'mac_602c'):
            self.assertIn(f'when={variable}<-32768;', scene)
            self.assertIn(f'when={variable}>32767;', scene)


if __name__ == '__main__':
    unittest.main()
