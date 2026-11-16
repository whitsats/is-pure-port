import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parent.parent
SAVE_DIR = ROOT / 'PCSX2/sstates'


class SnapshotCliTests(unittest.TestCase):
    def test_explicit_snapshot_advances_one_instruction_without_touching_save(self):
        states = list(SAVE_DIR.glob('SLPM-66570*.p2s'))
        if not states:
            self.skipTest('没有提供原有即时存档')
        save = states[0]
        before = hashlib.sha256(save.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'result.txt'
            result = subprocess.run([sys.executable, '-B', str(BASE / '转换器/emit_webgal.py'),
                                     '--script', 'MAC_001.bin', '--offset', '0x58', '--program',
                                     '--state-snapshot', str(save), '--allow-empty', '--output', str(out)],
                                    capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out.with_suffix('.txt.json').read_text(encoding='utf-8'))
            self.assertEqual(report['stop']['name'], 'quick_save')
            self.assertEqual(report['stop']['offset'], 0x60)
            self.assertEqual(report['state_writes'][0]['operation'], 'reg_calc_17_snapshot')
            self.assertEqual(report['state_snapshot']['sha256'], before)
            self.assertIn('不能当作原游戏实际运行轨迹', report['warning'])
        self.assertEqual(hashlib.sha256(save.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
