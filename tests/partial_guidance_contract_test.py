from copy import deepcopy
from types import SimpleNamespace
import unittest

from cloud_model import validate_all_zone


class PartialGuidanceContractTest(unittest.TestCase):
    def setUp(self):
        self.graph = SimpleNamespace(nodes={'N7':{},'N3':{}},exits={'X':{}},fallbacks={},
            adjacency={'N7':[],'N3':[],'X':[]},edges={
                'E10':{'from':'N7','to':'N3'}, 'E1':{'from':'N3','to':'X'}})
        self.stub = {'edgeId':'E10','towardNode':'N3','exitNode':'X',
                     'ledLogicalIndices':list(range(10,22))}
        self.plan = {'routingMode':'all_zones_to_exits','routeStatus':'ok',
            'availableExits':['X'],'guidedNodes':['N3'],'unreachableNodes':[],
            'ledExcludedEdges':['E10'],
            'directedEdges':[{'edgeId':'E1','from':'N3','to':'X','exitNode':'X'}],
            'partialEdges':[self.stub]}

    def check(self, plan=None, blocked_nodes=None, blocked_edges=None, red=None):
        return validate_all_zone(plan or self.plan,self.graph,
            ['N7'] if blocked_nodes is None else blocked_nodes, blocked_edges or [],
            list(range(5,10)) if red is None else red)

    def test_partial_suffix_is_not_a_route_through_the_fire(self):
        self.assertEqual(self.check(),self.plan)
        self.assertNotIn('N7',self.plan['guidedNodes'])

    def test_rejects_red_crossing_reversal_gaps_and_wrong_destination(self):
        for changes in ({'ledLogicalIndices':list(range(7,22))},
                        {'ledLogicalIndices':list(range(21,9,-1))},
                        {'ledLogicalIndices':[10,12,21]}, {'towardNode':'N7'},
                        {'exitNode':'N3'}, {'edgeId':'E1'}):
            plan = deepcopy(self.plan)
            plan['partialEdges'][0].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.check(plan)

    def test_rejects_unjustified_or_explicitly_closed_stub(self):
        for kwargs in ({'blocked_nodes':[]},{'blocked_edges':['E10']},
                       {'red':[]},{'red':list(range(5,22))}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                self.check(**kwargs)
