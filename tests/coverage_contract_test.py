"""Additional guidance must be a DAG of actual, unblocked exit-reaching edges."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from cloud_model import validate_all_zone
from hardware.real_ticket_overlay import prototype_floorplan


class CoverageContractTest(unittest.TestCase):
    def setUp(self):
        pairs = {'E3':('A','B'), 'E4':('B','X'), 'E5':('C','D'), 'E6':('D','X'),
                 'E01':('B','C'), 'E02':('D','A')}
        self.graph = SimpleNamespace(nodes=dict.fromkeys('ABCD'), exits={'X':{}}, fallbacks={},
            adjacency=dict.fromkeys('ABCDX'), edges={eid:{'from':a,'to':b} for eid,(a,b) in pairs.items()})
        self.plan = {'routingMode':'all_zones_to_exits','routeStatus':'ok',
                     'availableExits':['X'],'guidedNodes':list('ABCD'),'unreachableNodes':[],
                     'ledExcludedEdges':[], 'directedEdges':[
                         {'edgeId':eid,'from':a,'to':b,'exitNode':'X'}
                         for eid,(a,b) in pairs.items() if eid not in {'E01','E02'}]}
        self.extra = {'edgeId':'E01','from':'B','to':'C','exitNode':'X'}

    def test_old_report_and_new_branch_accepted(self):
        self.assertEqual(validate_all_zone(self.plan,self.graph,[],[]),self.plan)
        self.plan['coverageEdges'] = [self.extra]
        self.assertEqual(validate_all_zone(self.plan,self.graph,[],[]),self.plan)

    def test_two_individually_valid_branches_cannot_form_cycle(self):
        second = {'edgeId':'E02','from':'D','to':'A','exitNode':'X'}
        for edge in (self.extra, second):
            self.plan['coverageEdges'] = [edge]
            validate_all_zone(self.plan,self.graph,[],[])
        self.plan['coverageEdges'] = [self.extra, second]
        with self.assertRaisesRegex(ValueError,'순환'):
            validate_all_zone(self.plan,self.graph,[],[])

    def test_blocked_excluded_duplicate_wrong_destination_rejected(self):
        self.plan['coverageEdges'] = [self.extra]
        for blocked_nodes, blocked_edges in ((['C'],[]), ([],['E01'])):
            with self.assertRaises(ValueError):
                validate_all_zone(self.plan,self.graph,blocked_nodes,blocked_edges)
        for changes in ({'ledExcludedEdges':['E01']},
                        {'coverageEdges':[self.extra,self.extra]},
                        {'coverageEdges':[{**self.extra,'exitNode':'Y'}]},
                        {'coverageEdges':[{**self.extra,'to':'X'}]}):
            with self.assertRaises(ValueError):
                validate_all_zone({**self.plan,**changes},self.graph,[],[])

    def test_s2_overlay_preserves_original_and_rejects_partial_connection(self):
        source = {'nodes':[{'id':'N7'},{'id':'N14'}], 'edges':[], 'exits':[]}
        before = deepcopy(source)
        result = prototype_floorplan(source)
        self.assertEqual(source,before)
        self.assertEqual(prototype_floorplan(result),result)
        self.assertEqual(result['exits'][0]['id'],'EXIT_S2')
        result['edges'] = [e for e in result['edges'] if e['id'] != 'E39']
        with self.assertRaises(ValueError):
            prototype_floorplan(result)
