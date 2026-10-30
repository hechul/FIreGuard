from __future__ import annotations

import json
import math
import re
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

load_dotenv()

from state_manager import SimulationState
from route_service import FloorGraph
from cloud_api import install_cloud, enabled as cloud_enabled, deployment_info

BASE_DIR = Path(__file__).resolve().parent
FLOORPLAN_PATH = BASE_DIR / "static" / "data" / "floorplan.json"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "fireguard-local-demo")
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

with FLOORPLAN_PATH.open("r", encoding="utf-8") as file:
    floorplan = json.load(file)

state = SimulationState(floorplan, real_fire_path=BASE_DIR / "runtime" / "real_fire_latches.json")
cloud_plan = install_cloud(app, floorplan)


def broadcast_state() -> dict[str, Any]:
    snapshot = state.snapshot()
    socketio.emit("state:update", snapshot)
    return snapshot


def apply_action(action: Callable[[], None]):
    try:
        with state._lock:
            if request.path.startswith("/api/simulation/") and state.operation_mode != "simulation":
                return jsonify({"ok": False, "error": "SIMULATION 모드에서만 사용할 수 있습니다."}), 409
            action()
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    return jsonify({"ok": True, "state": broadcast_state()})


def payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("JSON 요청 본문이 필요합니다.")
    return data


@app.get("/")
def dashboard():
    return render_template("dashboard.html", floorplan=cloud_plan if cloud_enabled(app) else floorplan,
                           cloud_enabled=cloud_enabled(app), build_id=deployment_info()['buildId'])


@app.get("/mobile/<node_id>")
def mobile(node_id: str):
    return render_template("mobile.html", node_id=node_id)


@app.get("/3d")
def preview_3d():
    return render_template("3d_preview.html", floorplan=cloud_plan if cloud_enabled(app) else floorplan)


@app.get("/api/floorplan")
def get_floorplan():
    return jsonify(floorplan)


def _save_floorplan(candidate=None) -> None:
    """현재 floorplan을 JSON 파일에 안전하게 저장."""
    temp_path = FLOORPLAN_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(candidate if candidate is not None else floorplan, file, ensure_ascii=False, indent=2)
    temp_path.replace(FLOORPLAN_PATH)


@app.post("/api/floorplan/layout")
def update_floorplan_layout():
    """수정 모드의 좌표 및 추가 노드/간선을 검증한 뒤 함께 저장한다.

    Edge는 from/to Node 연결 관계로 계산되므로 별도 좌표를 가지지 않는다.
    편집 화면의 '간선 이동'은 연결된 두 끝점을 동시에 이동한다.
    """
    try:
        data = payload()
        positions = data.get("positions")
        if not isinstance(positions, dict):
            raise ValueError("positions 객체가 필요합니다.")

        with state._lock:
            if "baseFloorplan" in data and data["baseFloorplan"] != floorplan:
                return jsonify({"ok": False, "error": "다른 화면에서 지도가 변경되었습니다. 저장값을 다시 불러오세요."}), 409
            candidate = deepcopy(floorplan)

            deleted_nodes = set(data.get("deletedNodes", []))
            deleted_edges = set(data.get("deletedEdges", []))

            exit_ids = {item["id"] for item in candidate["exits"]}
            if any(d in exit_ids for d in deleted_nodes):
                raise ValueError("비상구(EXIT)는 삭제할 수 없습니다.")

            # Remove deleted nodes and connected edges/sensors
            if deleted_nodes:
                candidate["nodes"] = [n for n in candidate["nodes"] if n["id"] not in deleted_nodes]
                candidate["edges"] = [e for e in candidate["edges"] if e["from"] not in deleted_nodes and e["to"] not in deleted_nodes]
                if "fallbackDestinations" in candidate:
                    candidate["fallbackDestinations"] = [f for f in candidate["fallbackDestinations"] if f["id"] not in deleted_nodes]
                if "sensors" in candidate:
                    candidate["sensors"] = [s for s in candidate["sensors"] if s.get("node") not in deleted_nodes]

            # Remove deleted edges
            if deleted_edges:
                candidate["edges"] = [e for e in candidate["edges"] if e["id"] not in deleted_edges]

            # Prune shutters on removed edges
            remaining_edge_ids = {e["id"] for e in candidate["edges"]}
            if "shutters" in candidate:
                candidate["shutters"] = [s for s in candidate["shutters"] if s.get("edge") in remaining_edge_ids]

            editable = {item["id"]: item for item in [*candidate["nodes"], *candidate["exits"]]}
            new_nodes = data.get("nodes", [])
            new_edges = data.get("edges", [])
            if not isinstance(new_nodes, list) or not isinstance(new_edges, list):
                raise ValueError("추가할 노드와 간선은 목록이어야 합니다.")
            for node in new_nodes:
                if not isinstance(node, dict) or not re.fullmatch(r"N[1-9][0-9]*", str(node.get("id", ""))):
                    raise ValueError("노드 ID 형식이 올바르지 않습니다.")
                if node["id"] in editable or node["id"] not in positions:
                    raise ValueError("노드 ID가 중복되거나 좌표가 없습니다.")
                name = node.get("name", node["id"])
                if not isinstance(name, str) or not name.strip() or len(name) > 80:
                    raise ValueError("노드 이름은 1~80자로 입력하세요.")
                item = {"id": node["id"], "name": name.strip()}
                candidate["nodes"].append(item)
                editable[item["id"]] = item
            for item_id, point in positions.items():
                if item_id in deleted_nodes:
                    continue
                if item_id not in editable or not isinstance(point, dict):
                    raise ValueError(f"{item_id} 좌표 형식이 올바르지 않습니다.")
                x, y = float(point["x"]), float(point["y"])
                if not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError("좌표는 유한한 숫자여야 합니다.")
                editable[item_id].update(x=round(max(8, min(576, x)), 2), y=round(max(8, min(850, y)), 2))
            edge_ids = {edge["id"] for edge in candidate["edges"]}
            pairs = {frozenset((edge["from"], edge["to"])) for edge in candidate["edges"]}
            for edge in new_edges:
                if not isinstance(edge, dict) or not re.fullmatch(r"E[0-9]+", str(edge.get("id", ""))):
                    raise ValueError("간선 ID 형식이 올바르지 않습니다.")
                start, end = edge.get("from"), edge.get("to")
                if not isinstance(start, str) or not isinstance(end, str) or start not in editable or end not in editable or start == end:
                    raise ValueError("서로 다른 두 지점을 연결하세요.")
                pair = frozenset((start, end))
                if edge["id"] in edge_ids or pair in pairs:
                    raise ValueError("이미 존재하는 간선입니다.")
                weight = float(edge["weight"])
                if not math.isfinite(weight) or weight <= 0:
                    raise ValueError("간선 비용은 0보다 큰 유한한 숫자여야 합니다.")
                candidate["edges"].append({"id": edge["id"], "from": start, "to": end, "weight": weight})
                edge_ids.add(edge["id"])
                pairs.add(pair)
            if not positions and not new_edges and not deleted_nodes and not deleted_edges:
                raise ValueError("저장할 변경 사항이 없습니다.")

            # Update state references if needed
            if state.start_node in deleted_nodes:
                if candidate["nodes"]:
                    state.start_node = candidate["nodes"][0]["id"]
                elif candidate["exits"]:
                    state.start_node = candidate["exits"][0]["id"]
            state.blocked_nodes = {n for n in state.blocked_nodes if n not in deleted_nodes}
            state.blocked_edges = {e for e in state.blocked_edges if e in remaining_edge_ids}
            state.manual_blocked_edges = {e for e in state.manual_blocked_edges if e in remaining_edge_ids}

            active_sensor_ids = {s["id"] for s in candidate.get("sensors", [])}
            state.flame_sensors = {sid: val for sid, val in state.flame_sensors.items() if sid in active_sensor_ids}
            active_shutter_ids = {s["id"] for s in candidate.get("shutters", [])}
            state.shutters = {sid: val for sid, val in state.shutters.items() if sid in active_shutter_ids}
            graph = FloorGraph(candidate)
            _save_floorplan(candidate)
            floorplan.clear()
            floorplan.update(candidate)
            state.graph = graph
            state._recompute()
        socketio.emit("floorplan:update", floorplan)
        return jsonify({"ok": True, "floorplan": floorplan, "changed": len(positions), "state": broadcast_state()})
    except (ValueError, TypeError, KeyError) as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except OSError:
        return jsonify({"ok": False, "error": "지도를 파일에 저장하지 못했습니다. 다시 시도하세요."}), 500


@app.get("/api/state")
def get_state():
    snapshot = state.snapshot()
    start = request.args.get('startNode')
    if start is not None:
        if start not in state.graph.nodes:
            return jsonify(ok=False, error='알 수 없는 startNode입니다.'), 400
        route = state.graph.shortest_route(start, set(snapshot['blockedNodes']), set(snapshot['blockedEdges']), snapshot['edgeWeightOverrides'])
        if route is None:
            route = state.graph.shortest_fallback_route(start, set(snapshot['blockedNodes']), set(snapshot['blockedEdges']), snapshot['edgeWeightOverrides'])
        snapshot['startNode'] = start
        snapshot['route'] = route.as_dict() if route else None
        snapshot['fallbackActive'] = bool(route and route.route_mode == 'fallback')
        snapshot['routeMode'] = route.route_mode if route else 'none'
        snapshot['selectedDestinationName'] = state.graph.destination_name(route.destination_id) if route else None
        snapshot['selectedExitName'] = snapshot['selectedDestinationName']
        if route is None:
            snapshot['overallStatus'] = 'no_route'
    return jsonify(snapshot)


@app.post("/api/mode")
def set_mode():
    data = payload()
    return apply_action(lambda: state.set_operation_mode(data["mode"]))


@app.post("/api/simulation/start-node")
def set_start_node():
    data = payload()
    return apply_action(lambda: state.set_start_node(data["nodeId"], source="SIM"))


@app.post("/api/simulation/flame")
def set_flame():
    data = payload()
    return apply_action(lambda: state.set_flame(data["sensorId"], data["active"], source="SIM"))


@app.post("/api/simulation/node-fire")
def set_node_fire():
    data = payload()
    return apply_action(lambda: state.set_node_fire(data["nodeId"], data["active"], source="SIM"))


@app.post("/api/simulation/shutter")
def set_shutter():
    data = payload()
    return apply_action(lambda: state.set_shutter(data["shutterId"], data["closed"], source="SIM"))


@app.post("/api/simulation/manual-edge")
def set_manual_edge():
    data = payload()
    return apply_action(lambda: state.set_manual_edge(data["edgeId"], data["blocked"]))


@app.post("/api/simulation/connection")
def set_connection():
    data = payload()
    return apply_action(lambda: state.set_connection(data["target"], data["connected"], source="SIM"))



@app.post("/api/simulation/sensor-connection")
def set_sensor_connection():
    data = payload()
    return apply_action(lambda: state.set_sensor_connection(data["sensorId"], data["connected"], source="SIM"))


@app.post("/api/simulation/edge-weight")
def set_edge_weight():
    data = payload()
    value = data.get("weight")
    return apply_action(lambda: state.set_edge_weight(data["edgeId"], value, source="SIM"))


@app.post("/api/simulation/reset")
def reset():
    data = request.get_json(silent=True) or {}
    return apply_action(lambda: state.reset(clear_events=bool(data.get("clearEvents", False))))


@app.post("/api/simulation/scenario")
def run_scenario():
    data = payload()
    scenario_id = data["scenarioId"]

    def action():
        # -----------------------------------------------------------
        # BASIC
        # -----------------------------------------------------------
        if scenario_id == "normal":
            state.reset(clear_events=False)

        # -----------------------------------------------------------
        # SENSOR / FIRE
        # -----------------------------------------------------------
        elif scenario_id == "east_exit_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N10", True, source="SCENARIO")

        elif scenario_id == "ticket_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N14", True, source="SCENARIO")

        elif scenario_id == "cinema4_fire":
            state.reset(clear_events=False)
            state.set_node_fire("N9", True, source="SCENARIO")

        elif scenario_id == "large_fire":
            state.reset(clear_events=False)
            # 불꽃센서가 설치된 동측/서측 비상구 앞을 동시에 차단한다.
            state.set_node_fire("N10", True, source="SCENARIO")
            state.set_node_fire("N7", True, source="SCENARIO")

        # -----------------------------------------------------------
        # ROUTE / BLOCK / CROWD
        # -----------------------------------------------------------
        elif scenario_id == "east_shutter":
            state.reset(clear_events=False)
            state.set_shutter("SH-02", True, source="SCENARIO")

        elif scenario_id == "mid_route_block":
            state.reset(clear_events=False)
            # 정상 최단경로 N1-N33-N10-EXIT_E 중 E02가 갑자기 막힌 상황.
            state.set_manual_edge("E02", True)

        elif scenario_id == "crowd_congestion":
            state.reset(clear_events=False)
            # 차단은 아니지만 동측 통로 혼잡 비용을 크게 올려 Dijkstra가 다른 출구를 선택하게 한다.
            state.set_edge_weight("E02", 14.0, source="SCENARIO")
            state.set_edge_weight("E03", 8.0, source="SCENARIO")

        # -----------------------------------------------------------
        # FALLBACK / IMPOSSIBLE
        # -----------------------------------------------------------
        elif scenario_id == "fallback_toilet":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16"):
                state.set_manual_edge(edge_id, True)

        elif scenario_id == "fallback_descender":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16", "E21", "E22"):
                state.set_manual_edge(edge_id, True)

        elif scenario_id == "no_route":
            state.reset(clear_events=False)
            for edge_id in ("E03", "E09", "E12", "E16", "E21", "E22", "E23"):
                state.set_manual_edge(edge_id, True)

        # -----------------------------------------------------------
        # SYSTEM / COMMUNICATION
        # -----------------------------------------------------------
        elif scenario_id == "server_off":
            state.reset(clear_events=False)
            state.set_connection("server", False, source="SCENARIO")

        elif scenario_id == "fire_server_off":
            state.reset(clear_events=False)
            state.set_node_fire("N10", True, source="SCENARIO")
            state.set_connection("server", False, source="SCENARIO")

        elif scenario_id == "server_on":
            state.set_connection("server", True, source="SCENARIO")

        elif scenario_id == "pi_off":
            state.reset(clear_events=False)
            state.set_connection("pi", False, source="SCENARIO")

        elif scenario_id == "pi_on":
            state.set_connection("pi", True, source="SCENARIO")

        # -----------------------------------------------------------
        # SENSOR FAULT
        # -----------------------------------------------------------
        elif scenario_id == "sensor_fault":
            state.reset(clear_events=False)
            # 동측 비상구 불꽃 센서가 통신 단절된 상황.
            state.set_sensor_connection("FLM-15", False, source="SCENARIO")

        elif scenario_id == "sensor_recover":
            state.set_sensor_connection("FLM-15", True, source="SCENARIO")

        else:
            raise ValueError(f"알 수 없는 시나리오입니다: {scenario_id}")

    return apply_action(action)


# ---------------------------------------------------------------------------
# 실제 Raspberry Pi 연동용 API
# ---------------------------------------------------------------------------
@app.post("/api/hardware/heartbeat")
def hardware_heartbeat():
    def action():
        with state.hardware_input():
            state.hardware_heartbeat()

    return apply_action(action)


@app.post("/api/real/fire/clear")
def clear_real_fire():
    data = payload()

    def action():
        with state.hardware_input():
            state.clear_real_fire(data.get("sensorIds"))

    return apply_action(action)


@app.post("/api/hardware/flame")
def hardware_flame():
    data = payload()

    def action():
        with state.hardware_input():
            state.hardware_heartbeat()
            state.set_flame(data["sensorId"], data["active"], source="REAL")

    return apply_action(action)


@app.post("/api/hardware/batch")
def hardware_batch():
    """라즈베리파이가 한 번에 여러 센서 값을 전송할 때 사용한다.

    예시:
    {
      "flame": {"FLM-01": false, "FLM-07": true},
      "shutters": {"SH-01": false}
    }
    """
    data = payload()
    if "mq2" in data:
        return jsonify({"ok": False, "error": "MQ-2 입력은 지원하지 않습니다. batch에서 mq2 항목을 제거하세요."}), 400

    def action():
        with state.hardware_input():
            state.hardware_heartbeat()
            for sensor_id, active in (data.get("flame") or {}).items():
                state.set_flame(sensor_id, bool(active), source="REAL")
            for shutter_id, closed in (data.get("shutters") or {}).items():
                state.set_shutter(shutter_id, bool(closed), source="REAL")

    return apply_action(action)


@socketio.on("connect")
def socket_connected():
    emit("state:update", state.snapshot())


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8080, debug=True, use_reloader=False)
