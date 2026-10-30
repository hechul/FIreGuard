from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any

from route_service import FloorGraph


class SimulationState:
    """FireGuard의 단일 상태 저장소.

    실제 하드웨어와 시뮬레이션 상태를 모드별로 분리해 보관하며,
    UI/경로 계산 로직은 공통으로 사용한다.
    """

    MAX_EVENTS = 200
    REAL_FLAME_CONFIRM_SECONDS = 1.0
    REAL_FLAME_MAX_SAMPLE_GAP = 1.5
    MODE_FIELDS = ("start_node", "flame_sensors", "shutters",
                   "pi_connected", "server_link_connected", "connection_changed_at",
                   "manual_blocked_edges", "edge_weight_overrides", "events", "_flame_confirmation")

    def __init__(self, floorplan: dict[str, Any], real_fire_path: Path | None = None):
        self._lock = RLock()
        self.floorplan = floorplan
        self.graph = FloorGraph(floorplan)
        self.events: list[dict[str, str]] = []
        self.operation_mode = "simulation"
        self.manual_blocked_edges: set[str] = set()
        self._reset_state(clear_events=False)
        self._mode_states = {"real": self._capture_mode()}
        self._real_fire_path = real_fire_path
        self._real_latched_ids: set[str] = set()
        self._real_latches_dirty = False
        if real_fire_path is not None and real_fire_path.exists():
            stored = json.loads(real_fire_path.read_text(encoding="utf-8"))
            if not isinstance(stored, list) or not all(isinstance(sid, str) for sid in stored):
                raise ValueError("저장된 실제 화재 상태 형식이 올바르지 않습니다.")
            self._real_latched_ids = set(stored).intersection(self.flame_sensors)
            for sid in self._real_latched_ids:
                self._mode_states["real"]["flame_sensors"][sid].update(active=True, latched=True)
        self._add_event("SYSTEM", "관제 시스템", "초기화", "FireGuard 관제 시스템 준비 완료")

    def _persist_real_fire(self) -> None:
        if self._real_fire_path is None or not self._real_latches_dirty:
            return
        self._real_fire_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._real_fire_path.with_suffix(".tmp")
        temp.write_text(json.dumps(sorted(self._real_latched_ids)), encoding="utf-8")
        temp.replace(self._real_fire_path)
        self._real_latches_dirty = False

    def clear_real_fire(self, sensor_ids: list[str]) -> None:
        """Explicit dashboard action, called inside hardware_input()."""
        with self._lock:
            if not isinstance(sensor_ids, list) or not sensor_ids or not all(
                isinstance(sid, str) and sid in self.flame_sensors for sid in sensor_ids
            ):
                raise ValueError("해제할 불꽃 센서 ID 목록이 필요합니다.")
            remaining = self._real_latched_ids.difference(sensor_ids)
            # Save first: a failed manual clear must not silently drop the alarm.
            previous = self._real_latched_ids.copy()
            self._real_latched_ids = remaining
            self._real_latches_dirty = True
            try:
                self._persist_real_fire()
            except OSError:
                self._real_latched_ids = previous
                self._real_latches_dirty = True
                raise
            for sid in sorted(set(sensor_ids)):
                self._flame_confirmation.pop(sid, None)
                self.flame_sensors[sid].update(active=False, latched=False, updatedAt=self._now())
            self._recompute()
            self._add_event("CLEAR", ", ".join(sorted(set(sensor_ids))), "실제 화재 수동 해제 (MANUAL)", self._route_result_text())

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _reset_state(self, clear_events: bool = False) -> None:
        now = self._now()
        if clear_events:
            self.events.clear()

        # 시연 시 시작 위치는 매표소 우측(N1)을 기본값으로 사용한다.
        self.start_node = self.floorplan["nodes"][0]["id"]
        self.flame_sensors = {
            sensor["id"]: {"active": False, "connected": True, "updatedAt": now}
            for sensor in self.floorplan["sensors"]
            if sensor["type"] == "flame"
        }
        self._flame_confirmation: dict[str, tuple[float, float]] = {}
        self.shutters = {
            shutter["id"]: {"closed": False, "connected": True, "updatedAt": now}
            for shutter in self.floorplan.get("shutters", [])
        }
        self.pi_connected = True
        self.server_link_connected = True  # Supabase/외부 관제 링크 상태를 시연한다.
        self.connection_changed_at = {"pi": now, "server": now}
        self.manual_blocked_edges = set()
        self.edge_weight_overrides: dict[str, float] = {}
        self.route: dict[str, Any] | None = None
        self.blocked_nodes: set[str] = set()
        self.blocked_edges: set[str] = set()
        self._recompute()

    def _add_event(self, event_type: str, location: str, change: str, result: str) -> None:
        self.events.insert(
            0,
            {
                "timestamp": self._now(),
                "type": event_type,
                "location": location,
                "change": change,
                "result": result,
            },
        )
        del self.events[self.MAX_EVENTS :]

    def _sensor_config(self, sensor_id: str) -> dict[str, Any]:
        for sensor in self.floorplan["sensors"]:
            if sensor["id"] == sensor_id:
                return sensor
        raise ValueError(f"알 수 없는 센서입니다: {sensor_id}")

    def _recompute(self) -> None:
        blocked_nodes = {
            self._sensor_config(sensor_id)["node"]
            for sensor_id, sensor in self.flame_sensors.items()
            if sensor["active"] and (sensor["connected"] or sensor.get("latched", False))
        }

        shutter_edges = {
            shutter["edge"]
            for shutter in self.floorplan.get("shutters", [])
            if self.shutters[shutter["id"]]["closed"] and self.shutters[shutter["id"]]["connected"]
        }

        self.blocked_nodes = blocked_nodes
        self.blocked_edges = shutter_edges | self.manual_blocked_edges

        # 1순위는 정규 EXIT, 2순위는 지정된 화장실/완강기 보조 대피 지점이다.
        route = self.graph.shortest_route(
            self.start_node,
            blocked_nodes=self.blocked_nodes,
            blocked_edges=self.blocked_edges,
            edge_weight_overrides=self.edge_weight_overrides,
        )
        if route is None:
            route = self.graph.shortest_fallback_route(
                self.start_node,
                blocked_nodes=self.blocked_nodes,
                blocked_edges=self.blocked_edges,
                edge_weight_overrides=self.edge_weight_overrides,
            )
        self.route = route.as_dict() if route else None

    def _capture_mode(self):
        return {key: deepcopy(getattr(self, key)) for key in self.MODE_FIELDS}

    def _restore_mode(self, data):
        for key, value in data.items():
            setattr(self, key, deepcopy(value))
        # Map edits apply to both modes; discard references to deleted equipment.
        sensor_ids = {s["id"] for s in self.floorplan["sensors"]}
        self.flame_sensors = {k: v for k, v in self.flame_sensors.items() if k in sensor_ids}
        shutter_ids = {s["id"] for s in self.floorplan.get("shutters", [])}
        self.shutters = {k: v for k, v in self.shutters.items() if k in shutter_ids}
        self.manual_blocked_edges.intersection_update(self.graph.edges)
        self.edge_weight_overrides = {k: v for k, v in self.edge_weight_overrides.items() if k in self.graph.edges}
        if self.start_node not in self.graph.nodes:
            self.start_node = self.floorplan["nodes"][0]["id"]
        self._recompute()

    @contextmanager
    def hardware_input(self):
        """Update the real bank atomically without changing the selected mode."""
        with self._lock:
            if self.operation_mode == "real":
                yield
                return
            simulation = self._capture_mode()
            self._restore_mode(self._mode_states["real"])
            try:
                yield
            finally:
                self._mode_states["real"] = self._capture_mode()
                self._restore_mode(simulation)

    def _real_fire_sensor_ids(self):
        data = self._capture_mode() if self.operation_mode == "real" else self._mode_states["real"]
        valid = {s["id"] for s in self.floorplan["sensors"]}
        return sorted(
            [sid for sid, v in data["flame_sensors"].items() if sid in valid and v["active"] and (v["connected"] or v.get("latched", False))]
        )

    def set_operation_mode(self, mode: str) -> None:
        with self._lock:
            mode = str(mode).lower()
            if mode not in {"real", "simulation"}:
                raise ValueError("운영 모드는 real 또는 simulation이어야 합니다.")
            if self.operation_mode == mode:
                return
            before = self.operation_mode
            self._mode_states[before] = self._capture_mode()
            self._restore_mode(self._mode_states[mode])
            self.operation_mode = mode
            self._add_event("MODE", "관제 시스템", f"{before} → {mode}", "운영 모드 변경")

    def set_start_node(self, node_id: str, source: str = "SIM") -> None:
        with self._lock:
            if node_id not in self.graph.nodes:
                raise ValueError(f"알 수 없는 Node입니다: {node_id}")
            before = self.start_node
            self.start_node = node_id
            self._recompute()
            self._add_event("START", node_id, f"{before} → {node_id} ({source})", self._route_result_text())

    def set_flame(self, sensor_id: str, active: bool, source: str = "SIM") -> None:
        with self._lock:
            if sensor_id not in self.flame_sensors:
                raise ValueError(f"알 수 없는 불꽃센서입니다: {sensor_id}")
            if source == "REAL":
                now = monotonic()
                sensor = self.flame_sensors[sensor_id]
                if not active or not sensor["connected"]:
                    self._flame_confirmation.pop(sensor_id, None)
                    active = sensor_id in self._real_latched_ids
                else:
                    started, last = self._flame_confirmation.get(sensor_id, (now, now))
                    if now - last > self.REAL_FLAME_MAX_SAMPLE_GAP:
                        started = now
                    self._flame_confirmation[sensor_id] = (started, now)
                    active = sensor["active"] or now - started >= self.REAL_FLAME_CONFIRM_SECONDS
                if active and sensor_id not in self._real_latched_ids:
                    self._real_latched_ids.add(sensor_id)
                    self._real_latches_dirty = True
                sensor["latched"] = sensor_id in self._real_latched_ids
                sensor["updatedAt"] = self._now()
                # Pending readings are not fire events; repeated confirmed values
                # also must not fill the event log on every sample.
                if sensor["active"] == active:
                    self._persist_real_fire()
                    return
            self.flame_sensors[sensor_id].update({"active": bool(active), "updatedAt": self._now()})
            self._recompute()
            if source == "REAL":
                self._persist_real_fire()
            node = self._sensor_config(sensor_id)["node"]
            self._add_event(
                "FIRE" if active else "CLEAR",
                f"{sensor_id} / {node}",
                f"{'화재 감지' if active else '화재 해제'} ({source})",
                self._route_result_text(),
            )

    def set_node_fire(self, node_id: str, active: bool, source: str = "SIM") -> None:
        """선택 Node의 불꽃 센서로 화재를 설정하는 시연용 편의 기능."""
        with self._lock:
            if node_id not in self.graph.nodes:
                raise ValueError(f"알 수 없는 Node입니다: {node_id}")

            flame_ids = [
                sensor["id"]
                for sensor in self.floorplan["sensors"]
                if sensor["type"] == "flame" and sensor["node"] == node_id
            ]
            if not flame_ids:
                raise ValueError(f"{node_id}에 연결된 화재 센서가 없습니다.")

            now = self._now()
            for sensor_id in flame_ids:
                self.flame_sensors[sensor_id].update({"active": bool(active), "updatedAt": now})

            self._recompute()
            node_name = self.graph.nodes[node_id]["name"]
            linked = ", ".join(flame_ids)
            self._add_event(
                "FIRE" if active else "CLEAR",
                f"{node_id} / {node_name}",
                f"통합 화재 {'발생' if active else '해제'} ({source}: {linked})",
                self._route_result_text(),
            )

    def set_shutter(self, shutter_id: str, closed: bool, source: str = "SIM") -> None:
        with self._lock:
            if shutter_id not in self.shutters:
                raise ValueError(f"알 수 없는 방화셔터입니다: {shutter_id}")
            self.shutters[shutter_id].update({"closed": bool(closed), "updatedAt": self._now()})
            self._recompute()
            shutter = next(item for item in self.floorplan["shutters"] if item["id"] == shutter_id)
            self._add_event(
                "SHUTTER",
                shutter["name"],
                f"{'닫힘' if closed else '열림'} ({source})",
                self._route_result_text(),
            )

    def set_manual_edge(self, edge_id: str, blocked: bool) -> None:
        with self._lock:
            if edge_id not in self.graph.edges:
                raise ValueError(f"알 수 없는 Edge입니다: {edge_id}")
            if blocked:
                self.manual_blocked_edges.add(edge_id)
            else:
                self.manual_blocked_edges.discard(edge_id)
            self._recompute()
            self._add_event(
                "ROUTE",
                edge_id,
                "관리자 수동 차단" if blocked else "관리자 차단 해제",
                self._route_result_text(),
            )

    def set_edge_weight(self, edge_id: str, weight: float | None, source: str = "SIM") -> None:
        """혼잡/우회 시연용 동적 Edge 가중치.

        weight=None 이면 원래 floorplan 가중치로 복구한다.
        """
        with self._lock:
            if edge_id not in self.graph.edges:
                raise ValueError(f"알 수 없는 Edge입니다: {edge_id}")
            if weight is None:
                self.edge_weight_overrides.pop(edge_id, None)
                change = "혼잡 가중치 해제"
            else:
                weight = float(weight)
                if weight <= 0:
                    raise ValueError("Edge 가중치는 0보다 커야 합니다.")
                self.edge_weight_overrides[edge_id] = weight
                base = float(self.graph.edges[edge_id]["weight"])
                change = f"혼잡 가중치 {base:.1f} → {weight:.1f}"
            self._recompute()
            self._add_event("CONGESTION", edge_id, f"{change} ({source})", self._route_result_text())

    def set_sensor_connection(self, sensor_id: str, connected: bool, source: str = "SIM") -> None:
        """특정 센서 통신 단절/복구 시뮬레이션."""
        with self._lock:
            if sensor_id in self.flame_sensors:
                target = self.flame_sensors[sensor_id]
            else:
                raise ValueError(f"알 수 없는 센서입니다: {sensor_id}")
            target["connected"] = bool(connected)
            self._flame_confirmation.pop(sensor_id, None)
            if not connected and not target.get("latched", False):
                target["active"] = False
            target["updatedAt"] = self._now()
            self._recompute()
            self._add_event(
                "SENSOR",
                sensor_id,
                f"{'연결 복구' if connected else '통신 단절'} ({source})",
                self._route_result_text(),
            )

    def set_connection(self, target: str, connected: bool, source: str = "SIM") -> None:
        with self._lock:
            if target == "pi":
                self.pi_connected = bool(connected)
                if not connected:
                    self._flame_confirmation.clear()
                location = "Raspberry Pi"
            elif target == "server":
                self.server_link_connected = bool(connected)
                location = "Supabase / 외부 서버"
            else:
                raise ValueError("연결 대상은 pi 또는 server여야 합니다.")
            self.connection_changed_at[target] = self._now()
            if connected:
                result = "정상 통신"
            elif target == "server" and self.pi_connected:
                result = "외부 서버 없이 Raspberry Pi 로컬 Fail-safe 유지"
            else:
                result = "현장 제어기 단절 - 센서 수집/LED 출력 확인 필요"
            self._add_event(
                "CONNECTION",
                location,
                f"{'연결' if connected else '단절'} ({source})",
                result,
            )

    def reset(self, clear_events: bool = False) -> None:
        with self._lock:
            if self.operation_mode == "real":
                raise ValueError("실제 화재는 실제 화재 수동 해제 버튼으로 해제하세요.")
            mode = self.operation_mode
            self._reset_state(clear_events=clear_events)
            self.operation_mode = mode
            self._add_event("RESET", "전체 시스템", "상태 초기화", "기본 경로 복원")

    def hardware_heartbeat(self) -> None:
        with self._lock:
            was_connected = self.pi_connected
            self.pi_connected = True
            self.connection_changed_at["pi"] = self._now()
            if not was_connected:
                self._add_event("CONNECTION", "Raspberry Pi", "재연결 (REAL)", "실제 센서 입력 복구")

    def _route_result_text(self) -> str:
        if not self.route:
            return "사용 가능한 대피 경로 없음"
        destination_id = self.route.get("destinationId") or self.route["exitId"]
        destination_name = self.graph.destination_name(destination_id)
        if self.route.get("routeMode") == "fallback":
            return f"정규 비상구 불가 → {destination_name} 보조 대피 경로 계산 완료"
        return f"{destination_name} 경로 계산 완료"

    def _equipment_snapshot(self) -> list[dict[str, Any]]:
        equipment: list[dict[str, Any]] = [
            {
                "id": "CTRL-PI01",
                "category": "제어장치",
                "name": "Raspberry Pi 4",
                "location": "중앙 제어반",
                "status": "normal" if self.pi_connected else "offline",
                "stateLabel": "온라인" if self.pi_connected else "연결 끊김",
                "lastSeen": self.connection_changed_at["pi"],
            },
            {
                "id": "SERVER-01",
                "category": "서버",
                "name": "Supabase / 외부 관제 링크",
                "location": "네트워크",
                "status": "normal" if self.server_link_connected else "offline",
                "stateLabel": "연결됨" if self.server_link_connected else "연결 끊김",
                "lastSeen": self.connection_changed_at["server"],
            },
            {
                "id": "LED-CTRL01",
                "category": "유도장치",
                "name": "WS2812B 대피 유도 LED",
                "location": "주요 복도",
                "status": "normal" if self.pi_connected else "offline",
                "stateLabel": "경로 표시" if self.pi_connected and self.route else "대기" if self.pi_connected else "제어기 단절",
                "lastSeen": self.connection_changed_at["pi"],
            },
            {
                "id": "PSU-01",
                "category": "전원장치",
                "name": "LRS-100-5",
                "location": "중앙 제어반",
                "status": "normal",
                "stateLabel": "정상 공급",
                "lastSeen": self._now(),
            },
        ]

        for sensor in self.floorplan["sensors"]:
            sensor_id = sensor["id"]
            location = f"{sensor['node']} / {self.graph.nodes[sensor['node']]['name']}"
            if sensor["type"] == "flame":
                current = self.flame_sensors[sensor_id]
                status = "offline" if not current["connected"] else "danger" if current["active"] else "normal"
                label = "연결 끊김" if status == "offline" else "화재 감지" if status == "danger" else "정상"
                name = "불꽃 감지 센서"
                value = "1" if current["active"] else "0"

            equipment.append(
                {
                    "id": sensor_id,
                    "category": "센서",
                    "name": name,
                    "location": location,
                    "status": status,
                    "stateLabel": label,
                    "value": value,
                    "lastSeen": current["updatedAt"],
                }
            )

        for shutter in self.floorplan.get("shutters", []):
            current = self.shutters[shutter["id"]]
            status = "offline" if not current["connected"] else "warning" if current["closed"] else "normal"
            equipment.append(
                {
                    "id": shutter["id"],
                    "category": "방화설비",
                    "name": shutter["name"],
                    "location": shutter["edge"],
                    "status": status,
                    "stateLabel": "연결 끊김" if status == "offline" else "닫힘" if current["closed"] else "열림",
                    "lastSeen": current["updatedAt"],
                }
            )

        return equipment

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            fire_ids = [sid for sid, value in self.flame_sensors.items() if value["active"] and (value["connected"] or value.get("latched", False))]
            sensor_offline_ids = [
                sid for sid, value in self.flame_sensors.items()
                if not value["connected"]
            ]

            route_mode = self.route.get("routeMode", "exit") if self.route else "none"

            if not self.route:
                overall_status = "no_route"
            elif fire_ids:
                overall_status = "fire"
            elif route_mode == "fallback":
                overall_status = "warning"
            else:
                overall_status = "normal"

            fail_safe_active = self.pi_connected and not self.server_link_connected
            destination_name = None
            destination_type = None
            if self.route:
                destination_id = self.route.get("destinationId") or self.route["exitId"]
                destination_name = self.graph.destination_name(destination_id)
                destination_type = self.route.get("destinationType", "exit")

            return {
                "updatedAt": self._now(),
                "overallStatus": overall_status,
                "operationMode": self.operation_mode,
                "realFireSensorIds": self._real_fire_sensor_ids(),
                "realFireDetected": bool(self._real_fire_sensor_ids()),
                "failSafeActive": fail_safe_active,
                "startNode": self.start_node,
                "route": deepcopy(self.route),
                "routeMode": route_mode,
                "fallbackActive": route_mode == "fallback",
                "selectedExitName": destination_name,
                "selectedDestinationName": destination_name,
                "selectedDestinationType": destination_type,
                "blockedNodes": sorted(self.blocked_nodes),
                "blockedEdges": sorted(self.blocked_edges),
                "manualBlockedEdges": sorted(self.manual_blocked_edges),
                "edgeWeightOverrides": deepcopy(self.edge_weight_overrides),
                "congestionActive": bool(self.edge_weight_overrides),
                "connections": {"pi": self.pi_connected, "server": self.server_link_connected},
                "connectionChangedAt": deepcopy(self.connection_changed_at),
                "flameSensors": deepcopy(self.flame_sensors),
                "shutters": deepcopy(self.shutters),
                "sensorCounts": {
                    "flameTotal": len(self.flame_sensors),
                    "flameActive": len(fire_ids),
                    "offline": len(sensor_offline_ids),
                },
                "equipment": self._equipment_snapshot(),
                "events": deepcopy(self.events),
            }
