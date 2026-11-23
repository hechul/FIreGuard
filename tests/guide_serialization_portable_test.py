"""Test the production pure serializer without Linux device-lock imports."""
import ast
from pathlib import Path
import unittest


class GuideSerializationPortableTest(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[1] / 'hardware/real_device_runtime.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'prepare_guide_commands')
        namespace = {}
        exec(compile(ast.Module(body=[func],type_ignores=[]),str(source),'exec'),namespace)
        self.serialize = namespace['prepare_guide_commands']
        self.wire = lambda i: i + (i >= 20)

    def test_shared_endpoint_compression_preserves_all_pixels(self):
        plan = {'directedEdges':[{'ledLogicalIndices':list(range(162))}],
                'coverageEdges':[{'ledLogicalIndices':[0,1]}],
                'ledLogicalIndices':list(range(162)), 'fireLedLogicalIndices':[]}
        commands = self.serialize(plan,self.wire)
        segments = [list(map(int,c.split()[1:])) for c in commands if c.startswith('SEG ')]
        self.assertLessEqual(sum(map(len,segments)),163)
        moving_pixels = {pixel for segment in segments if len(segment) > 1 for pixel in segment}
        self.assertFalse(any(len(s) == 1 and s[0] in moving_pixels for s in segments),
                         'Compression must not leave a stationary head over a moving branch')
        self.assertEqual({i for s in segments for i in s},{self.wire(i) for i in range(162)})
        self.assertTrue(all(len(c.encode('ascii')) <= 94 for c in commands))

    def test_opposing_additional_branch_rejected_before_compression(self):
        plan = {'directedEdges':[{'ledLogicalIndices':[0,1]}],
                'coverageEdges':[{'ledLogicalIndices':[1,0]}],
                'ledLogicalIndices':[0,1], 'fireLedLogicalIndices':[]}
        with self.assertRaisesRegex(ValueError,'반대 방향'):
            self.serialize(plan,self.wire)

    def test_dim_green_blue_and_room5_shared_endpoint(self):
        plan = {'directedEdges':[{'ledLogicalIndices':[161,160,159,158]},
                                 {'ledLogicalIndices':[158]}],
                'ledLogicalIndices':[158,159,160,161], 'fireLedLogicalIndices':[110]}
        commands = self.serialize(plan,self.wire)
        self.assertIn('SEG 162 161 160 159',commands)
        self.assertNotIn('SEG 159',commands, 'Shared junction must not be a stationary blue head')
        self.assertIn('FIRE 111',commands)
        self.assertEqual(commands[-1], 'GUIDE 200 0 6 0 0 0 12')
