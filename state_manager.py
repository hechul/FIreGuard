from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any

from route_service import FloorGraph


class SimulationState:
    """FireGuard의 단일 상태 저장소.

    실제 하드웨어 이벤트와 시뮬레이션 이벤트가 동일한 메서드를 사용하도록
    구성해 UI/경로 계산 로직을 한 곳에서 유지한다.
    """

    MQ2_WARNING = 350
    MQ2_DANGER = 650
    MAX_EVENTS = 200

    def __init__(self, floorplan: dict[str, Any]):
        self._lock = RLock()
        self.floorplan = floorplan
        self.graph = FloorGraph(floorplan)
        self.events: list[dict[str, str]] = []
        self.operation_mode = "simulation"
        self.manual_blocked_edges: set[str] = set()
        self._reset_state(clear_events=False)
        self._add_event("SYSTEM", "관제 시스템", "초기화", "FireGuard 관제 시스템 준비 완료")

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
        self.mq2_sensors = {
            sensor["id"]: {"value": 0, "connected": True, "status": "normal", "updatedAt": now}
            for sensor in self.floorplan["sensors"]
            if sensor["type"] == "mq2"
        }
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
            if sensor["active"] and sensor["connected"]
        }
        blocked_nodes.update(
            self._sensor_config(sensor_id)["node"]
            for sensor_id, sensor in self.mq2_sensors.items()
            if sensor["status"] == "danger" and sensor["connected"]
        )

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

    def set_operation_mode(self, mode: str) -> None:
        with self._lock:
            mode = str(mode).lower()
            if mode not in {"real", "simulation"}:
                raise ValueError("운영 모드는 real 또는 simulation이어야 합니다.")
            if self.operation_mode == mode:
                return
            before = self.operation_mode
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
            self.flame_sensors[sensor_id].update({"active": bool(active), "updatedAt": self._now()})
            self._recompute()
            node = self._sensor_config(sensor_id)["node"]
            self._add_event(
                "FIRE" if active else "CLEAR",
                f"{sensor_id} / {node}",
                f"{'화재 감지' if active else '화재 해제'} ({source})",
                self._route_result_text(),
            )

    def set_mq2(self, sensor_id: str, value: int, source: str = "SIM") -> None:
        with self._lock:
            if sensor_id not in self.mq2_sensors:
                raise ValueError(f"알 수 없는 MQ-2 센서입니다: {sensor_id}")
            value = max(0, min(1023, int(value)))
            previous = self.mq2_sensors[sensor_id]["status"]
            status = "danger" if value >= self.MQ2_DANGER else "warning" if value >= self.MQ2_WARNING else "normal"
            self.mq2_sensors[sensor_id].update({"value": value, "status": status, "updatedAt": self._now()})
            self._recompute()
            self._add_event(
                "MQ2",
                sensor_id,
                f"{previous} → {status} / {value} ({source})",
                self._route_result_text(),
            )

    def set_node_fire(self, node_id: str, active: bool, source: str = "SIM") -> None:
        """선택 Node의 Flame과 MQ-2를 묶어서 바꾸는 시연용 편의 기능."""
        with self._lock:
            if node_id not in self.graph.nodes:
                raise ValueError(f"알 수 없는 Node입니다: {node_id}")

            flame_ids = [
                sensor["id"]
                for sensor in self.floorplan["sensors"]
                if sensor["type"] == "flame" and sensor["node"] == node_id
            ]
            mq2_ids = [
                sensor["id"]
                for sensor in self.floorplan["sensors"]
                if sensor["type"] == "mq2" and sensor["node"] == node_id
            ]
            if not flame_ids and not mq2_ids:
                raise ValueError(f"{node_id}에 연결된 화재 센서가 없습니다.")

            now = self._now()
            for sensor_id in flame_ids:
                self.flame_sensors[sensor_id].update({"active": bool(active), "updatedAt": now})
            for sensor_id in mq2_ids:
                value = 760 if active else 0
                self.mq2_sensors[sensor_id].update(
                    {"value": value, "status": "danger" if active else "normal", "updatedAt": now}
                )

            self._recompute()
            node_name = self.graph.nodes[node_id]["name"]
            linked = ", ".join([*flame_ids, *mq2_ids])
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
            elif sensor_id in self.mq2_sensors:
                target = self.mq2_sensors[sensor_id]
            else:
                raise ValueError(f"알 수 없는 센서입니다: {sensor_id}")
            target["connected"] = bool(connected)
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
            else:
                current = self.mq2_sensors[sensor_id]
                status = "offline" if not current["connected"] else current["status"]
                label = "연결 끊김" if status == "offline" else f"측정값 {current['value']}"
                name = "MQ-2 연기/가스 센서"
                value = str(current["value"])

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
            fire_ids = [sid for sid, value in self.flame_sensors.items() if value["active"] and value["connected"]]
            mq_danger_ids = [sid for sid, value in self.mq2_sensors.items() if value["status"] == "danger" and value["connected"]]
            mq_warning_ids = [sid for sid, value in self.mq2_sensors.items() if value["status"] == "warning" and value["connected"]]
            sensor_offline_ids = [
                sid for sid, value in {**self.flame_sensors, **self.mq2_sensors}.items()
                if not value["connected"]
            ]

            route_mode = self.route.get("routeMode", "exit") if self.route else "none"

            if not self.route:
                overall_status = "no_route"
            elif fire_ids or mq_danger_ids:
                overall_status = "fire"
            elif route_mode == "fallback" or mq_warning_ids:
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
                "mq2Sensors": deepcopy(self.mq2_sensors),
                "shutters": deepcopy(self.shutters),
                "sensorCounts": {
                    "flameTotal": len(self.flame_sensors),
                    "flameActive": len(fire_ids),
                    "mq2Total": len(self.mq2_sensors),
                    "mq2Danger": len(mq_danger_ids),
                    "mq2Warning": len(mq_warning_ids),
                    "offline": len(sensor_offline_ids),
                },
                "equipment": self._equipment_snapshot(),
                "events": deepcopy(self.events),
            }
