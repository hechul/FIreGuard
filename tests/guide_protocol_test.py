import unittest
from hardware.real_device_runtime import prepare_guide_commands, RealLedController
from hardware.cloud_sim_led import GuardedUno


def wire(i): return i + (i >= 20)


class GuideProtocolTest(unittest.TestCase):
    def test_directed_segments_single_conversion_and_red_only(self):
        plan = {'directedEdges': [{'ledLogicalIndices':[19,20,21]},
                                  {'ledLogicalIndices':[21,22]}],
                'ledLogicalIndices':[19,20,21,22], 'fireLedLogicalIndices':[18,23]}
        self.assertEqual(prepare_guide_commands(plan, wire),
            ['BEGIN', 'SEG 19 21 22', 'SEG 22 23', 'FIRE 18 24',
             'GUIDE 200 0 2 0 0 16 0'])
        self.assertEqual(prepare_guide_commands({'directedEdges':[],
            'ledLogicalIndices':[], 'fireLedLogicalIndices':[20]},wire),
            ['BEGIN','FIRE 21','GUIDE 200 0 2 0 0 16 0'])

    def test_bounds_conflicts_and_consistency_rejected_before_commands(self):
        invalid = [
            {'directedEdges':[{'ledLogicalIndices':[0,1]}, {'ledLogicalIndices':[1,0]}],
             'ledLogicalIndices':[0,1], 'fireLedLogicalIndices':[]},
            {'directedEdges':[{'ledLogicalIndices':list(range(162))}, {'ledLogicalIndices':[0,1]}],
             'ledLogicalIndices':list(range(162)), 'fireLedLogicalIndices':[]},
            {'directedEdges':[{'ledLogicalIndices':[0]} for _ in range(41)],
             'ledLogicalIndices':[0], 'fireLedLogicalIndices':[]},
            {'directedEdges':[{'ledLogicalIndices':[0]}], 'ledLogicalIndices':[0], 'fireLedLogicalIndices':[0]},
            {'directedEdges':[{'ledLogicalIndices':[0]}], 'ledLogicalIndices':[0,1], 'fireLedLogicalIndices':[]},
        ]
        for plan in invalid:
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                prepare_guide_commands(plan,wire)

    def test_long_segment_lines_are_within_firmware_limit(self):
        logical=list(range(100))
        commands=prepare_guide_commands({'directedEdges':[{'ledLogicalIndices':logical}],
            'ledLogicalIndices':logical, 'fireLedLogicalIndices':[]},wire)
        self.assertTrue(all(len(s.encode('ascii')) <= 94 for s in commands))
        actual=[int(i) for cmd in commands if cmd.startswith('SEG ') for i in cmd.split()[1:]]
        self.assertEqual(actual,[wire(i) for i in logical])

    def test_serial_rejection_does_not_fall_back(self):
        class Sim:
            def __init__(self): self.calls=[]
            def command(self, name):
                self.calls.append(name)
                if name.startswith('SEG '): raise RuntimeError('ERR')
        uno=Sim()
        with self.assertRaises(RuntimeError): GuardedUno.guide(uno,['BEGIN','SEG 0 1','GUIDE 200 0 2 0 0 16 0'])
        self.assertEqual(uno.calls,['BEGIN','SEG 0 1'])

if __name__ == '__main__': unittest.main()
