"""回放/录像系统"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field

REPLAY_VERSION = 2
MIN_SUPPORTED_VERSION = 1
FLOAT_TOLERANCE = 1e-9


@dataclass
class InputEvent:
    frame: int
    key: str
    value: float
    timestamp: float = 0.0
    latency: float = 0.0


@dataclass
class StateSnapshot:
    frame: int
    state: dict = field(default_factory=dict)
    delta: dict = field(default_factory=dict)


class ReplaySystem:
    def __init__(self, random_seed: int = 0):
        self.inputs: list = []
        self.snapshots: list = []
        self.physics_states: list = []
        self.random_seed: int = random_seed

    def set_random_seed(self, seed: int) -> None:
        self.random_seed = seed

    def record_input(self, key: str, value: float, frame: int,
                     timestamp: float = None, latency: float = 0.0) -> None:
        if timestamp is None:
            timestamp = time.time()
        self.inputs.append(InputEvent(frame, key, value, timestamp, latency))

    def record_physics_state(self, frame: int, state: dict) -> None:
        self.physics_states.append({"frame": frame, "state": copy.deepcopy(state)})

    def take_snapshot(self, frame: int, state: dict) -> None:
        state = copy.deepcopy(state)
        if not self.snapshots:
            self.snapshots.append(StateSnapshot(frame, state=state))
            return
        previous = self._reconstruct_state(len(self.snapshots) - 1)
        delta = {k: v for k, v in state.items() if previous.get(k) != v}
        removed = [k for k in previous if k not in state]
        if removed:
            delta["__removed__"] = removed
        self.snapshots.append(StateSnapshot(frame, delta=delta))

    def _reconstruct_state(self, snap_index: int) -> dict:
        state: dict = {}
        for snap in self.snapshots[: snap_index + 1]:
            full = getattr(snap, "state", None)
            if full:
                state = copy.deepcopy(full)
            delta = getattr(snap, "delta", None) or {}
            for key in delta.get("__removed__", []):
                state.pop(key, None)
            for key, value in delta.items():
                if key != "__removed__":
                    state[key] = copy.deepcopy(value)
        return state

    def _apply_input(self, state: dict, event) -> None:
        key, value = event.key, event.value
        if key in ("hit", "damage"):
            state["hp"] = state.get("hp", 0) - value
        elif key == "heal":
            state["hp"] = state.get("hp", 0) + value
        elif isinstance(state.get(key), (int, float)):
            state[key] -= value

    def seek_replay(self, target_frame: int) -> dict:
        # 快进/快退统一处理：从目标帧之前最近的快照重建完整状态，
        # 再顺序重放中间输入，倒放（目标帧早于当前位置）同样重新计算。
        base_index = -1
        for i, snap in enumerate(self.snapshots):
            if snap.frame <= target_frame:
                base_index = i
            else:
                break
        if base_index >= 0:
            state = self._reconstruct_state(base_index)
            start_frame = self.snapshots[base_index].frame
        else:
            state = {}
            start_frame = 0
        for event in self.inputs:
            if start_frame < event.frame <= target_frame:
                self._apply_input(state, event)
        return state

    def check_determinism(self, replay1: list, replay2: list) -> bool:
        return self._deterministic_equal(replay1, replay2)

    def _deterministic_equal(self, a, b) -> bool:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return abs(float(a) - float(b)) <= FLOAT_TOLERANCE
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(
                self._deterministic_equal(x, y) for x, y in zip(a, b)
            )
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(
                self._deterministic_equal(a[k], b[k]) for k in a
            )
        return a == b

    def export_replay(self, path: str) -> bool:
        payload = {
            "version": REPLAY_VERSION,
            "random_seed": self.random_seed,
            "inputs": [
                {
                    "frame": e.frame,
                    "key": e.key,
                    "value": e.value,
                    "timestamp": getattr(e, "timestamp", 0.0),
                    "latency": getattr(e, "latency", 0.0),
                }
                for e in self.inputs
            ],
            "snapshots": [
                {
                    "frame": s.frame,
                    "state": getattr(s, "state", {}) or {},
                    "delta": getattr(s, "delta", {}) or {},
                }
                for s in self.snapshots
            ],
            "physics_states": copy.deepcopy(self.physics_states),
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        envelope = json.dumps(
            {"checksum": hashlib.sha256(raw).hexdigest(), "payload": payload}
        ).encode("utf-8")
        with gzip.open(path, "wb") as f:
            f.write(envelope)
        return True

    def load_replay(self, path: str) -> dict:
        try:
            with gzip.open(path, "rb") as f:
                envelope = json.loads(f.read().decode("utf-8"))
        except (OSError, EOFError, json.JSONDecodeError) as exc:
            raise ValueError(f"回放文件损坏或格式非法: {path}") from exc
        payload = envelope.get("payload")
        if not isinstance(payload, dict) or "checksum" not in envelope:
            raise ValueError(f"回放文件缺少校验信息: {path}")
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != envelope["checksum"]:
            raise ValueError(f"回放文件校验失败（数据已损坏）: {path}")
        return self._migrate(payload)

    def _migrate(self, payload: dict) -> dict:
        version = payload.get("version", 1)
        if version > REPLAY_VERSION:
            raise ValueError(f"回放版本过新（v{version}），当前支持到 v{REPLAY_VERSION}")
        if version < MIN_SUPPORTED_VERSION:
            raise ValueError(f"回放版本过旧（v{version}），不再支持")
        if version == 1:
            for event in payload.get("inputs", []):
                event.setdefault("timestamp", 0.0)
                event.setdefault("latency", 0.0)
            payload.setdefault("random_seed", 0)
            payload.setdefault("physics_states", [])
            payload["version"] = REPLAY_VERSION
        return payload
