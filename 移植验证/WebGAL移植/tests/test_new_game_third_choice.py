import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / '转换器'))
from 探索后续选项 import analyze


class ThirdChoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = analyze(BASE / '数据/新游戏第二选项路径分析_拆分修复2.json')

    def test_condition_hides_option_only_for_recorded_predecessors(self):
        plans = {tuple(p['history']): p['choice'] for p in self.report['choice_plans']}
        self.assertEqual(len(plans), 12)
        self.assertEqual({k for k, v in plans.items() if v['visible_indices'] == [1, 2]},
                         {(1, 0), (1, 2), (1, 3)})
        for plan in plans.values():
            self.assertEqual(plan['options'][0]['condition']['raw'], '0x6010')
            self.assertEqual(bool(plan['options'][0]['condition_value']), 0 in plan['visible_indices'])

    def test_visible_paths_keep_original_indices_and_reach_fourth_choice(self):
        paths = self.report['paths']
        self.assertEqual(len(paths), 33)
        self.assertFalse(self.report['blocked_predecessors'])
        for path in paths:
            self.assertEqual((path['stop']['script'], path['stop']['offset'], path['stop']['name']),
                             ('MAC_003.bin', 0x34AC, 'sel_disp4'))
            self.assertEqual(path['state_bytes_at_stop']['0022E'], path['history'][2])


if __name__ == '__main__':
    unittest.main()
