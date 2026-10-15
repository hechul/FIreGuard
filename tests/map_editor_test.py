"""Map edits must persist atomically and rebuild the live routing graph."""
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as server
from state_manager import SimulationState


class MapEditorTest(unittest.TestCase):
    def setUp(self):
        self.original = deepcopy(server.floorplan)
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "floorplan.json"
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.path_patch = patch.object(server, "FLOORPLAN_PATH", self.path)
        self.path_patch.start()
        server.state = SimulationState(server.floorplan)
        self.client = server.app.test_client()

    def tearDown(self):
        server.floorplan.clear()
        server.floorplan.update(self.original)
        server.state = SimulationState(server.floorplan)
        self.path_patch.stop()
        self.temp.cleanup()

    def post(self, **body):
        return self.client.post('/api/floorplan/layout', json=body)

    def test_add_move_save_and_route(self):
        node_id = 'N' + str(max(int(n['id'][1:]) for n in self.original['nodes']) + 1)
        edge_id = 'E' + str(max(int(e['id'][1:]) for e in self.original['edges']) + 1)
        response = self.post(
            baseFloorplan=self.original,
            positions={"N33": {"x": 400, "y": 480}, node_id: {"x": 470, "y": 500}},
            nodes=[{"id": node_id, "name": "테스트 노드"}],
            edges=[{"id": edge_id, "from": node_id, "to": "EXIT_E", "weight": 1}],
        )
        self.assertEqual(response.status_code, 200)
        server.state.set_start_node(node_id)
        self.assertEqual(server.state.snapshot()["route"]["edges"], [edge_id])
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, server.floorplan)
        self.assertEqual(next(n for n in persisted["nodes"] if n["id"] == "N33")["x"], 400)
        reloaded = SimulationState(persisted)
        reloaded.set_start_node(node_id)
        self.assertEqual(reloaded.snapshot()["route"]["edges"], [edge_id])

    def test_invalid_edits_leave_memory_and_file_unchanged(self):
        before = self.path.read_bytes()
        invalid = [
            {"positions": {"N1": {"x": 100, "y": 100}, "N33": {"x": "bad", "y": 0}}},
            {"positions": {"N1": {"x": float('nan'), "y": 100}}},
            {"positions": {}, "edges": [{"id": "E24", "from": "N33", "to": "N1", "weight": 1}]},
            {"positions": {}, "edges": [{"id": "E24", "from": "N1", "to": "N999", "weight": 1}]},
            {"positions": {}, "edges": [{"id": "E24", "from": "N1", "to": "N10", "weight": -1}]},
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.assertEqual(self.post(**body).status_code, 400)
                self.assertEqual(server.floorplan, self.original)
                self.assertEqual(self.path.read_bytes(), before)

    def test_disk_failure_and_conflict(self):
        positions = {"N1": {"x": 200, "y": 300}}
        with patch.object(server, '_save_floorplan', side_effect=OSError):
            self.assertEqual(self.post(positions=positions).status_code, 500)
        self.assertEqual(server.floorplan, self.original)
        self.assertEqual(self.post(positions=positions, baseFloorplan={}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
