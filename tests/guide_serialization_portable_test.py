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
        self.assertEqual({i for s in segments for i in s},{self.wire(i) for i in range(162)})
        self.assertTrue(all(len(c.encode('ascii')) <= 94 for c in commands))

    def test_opposing_additional_branch_rejected_before_compression(self):
        plan = {'directedEdges':[{'ledLogicalIndices':[0,1]}],
                'coverageEdges':[{'ledLogicalIndices':[1,0]}],
                'ledLogicalIndices':[0,1], 'fireLedLogicalIndices':[]}
        with self.assertRaisesRegex(ValueError,'반대 방향'):
            self.serialize(plan,self.wire)
