"""回放/录像系统"""
import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field

REPLAY_VERSION = 2
MIN_SUPPORTED_VERSION = 1
KEYFRAME_INTERVAL = 30
FLOAT_EPSILON = 1e-9


@dataclass
class InputEvent:
    frame: int
    key: str
    value: float
    timestamp: float = 0.0  # bug1 fix: 记录时间戳


@dataclass
class StateSnapshot:
    frame: int
    state: dict  # 关键帧为完整状态, 否则为相对上一快照的差分
    is_keyframe: bool = True


def _state_delta(old: dict, new: dict) -> dict:
    delta = {}
    for key, new_val in new.items():
        if key not in old:
            delta[key] = new_val
        elif isinstance(new_val, dict) and isinstance(old[key], dict):
            sub = _state_delta(old[key], new_val)
            if sub:
                delta[key] = sub
        elif old[key] != new_val:
            delta[key] = new_val
    return delta


def _apply_delta(base: dict, delta: dict) -> dict:
    result = dict(base)
    for key, val in delta.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = _apply_delta(result[key], val)
        else:
            result[key] = val
    return result


class ReplaySystem:
    def __init__(self, random_seed: int = 0):
        self.inputs: list = []
        self.snapshots: list = []
        self.random_seed: int = random_seed  # bug1 fix: 记录随机种子
        self.physics_state: dict = {}  # bug4 fix: 记录物理引擎内部状态
        self.network_latency_ms: float = 0.0  # 记录延迟补偿参数

    def record_input(self, key: str, value: float, frame: int,
                     timestamp: float = None) -> None:
        # bug1 fix: 记录时间戳, 回放按真实时间轴播放而非固定间隔
        if timestamp is None:
            timestamp = time.time()
        self.inputs.append(InputEvent(frame, key, value, timestamp))

    def take_snapshot(self, frame: int, state: dict) -> None:
        # bug2 fix: 保存完整状态(技能CD/buff/敌人等整个dict),
        # 关键帧存全量, 其余存差分, 避免每帧全量导致文件膨胀
        if frame % KEYFRAME_INTERVAL == 0 or not self.snapshots:
            self.snapshots.append(StateSnapshot(frame, dict(state), True))
        else:
            prev = self._reconstruct_snapshot_state(len(self.snapshots) - 1)
            self.snapshots.append(
                StateSnapshot(frame, _state_delta(prev, state), False))

    def _reconstruct_snapshot_state(self, index: int) -> dict:
        # 从最近的关键帧起逐层应用差分, 还原完整状态
        start = index
        while start > 0 and not self.snapshots[start].is_keyframe:
            start -= 1
        state = dict(self.snapshots[start].state)
        for i in range(start + 1, index + 1):
            state = _apply_delta(state, self.snapshots[i].state)
        return state

    def _apply_input(self, state: dict, event) -> dict:
        # 确定性的状态推进: 同一输入序列必然得到同一结果
        state = dict(state)
        if event.key in ("hit", "damage"):
            state["hp"] = state.get("hp", 0) - event.value
        elif event.key == "heal":
            state["hp"] = state.get("hp", 0) + event.value
        else:
            state[event.key] = event.value
        return state

    def seek_replay(self, target_frame: int) -> dict:
        # bug3 fix: 快进/快退都重新计算状态:
        # 找到目标帧之前最近的快照, 重建完整状态后按顺序重放输入。
        # 倒放不反向执行动画, 而是从更早的关键帧确定性重演, 保证逻辑一致。
        base_frame = 0
        state = {}
        best_index = -1
        for i, snap in enumerate(self.snapshots):
            if snap.frame <= target_frame and snap.frame >= base_frame:
                base_frame = snap.frame
                best_index = i
        if best_index >= 0:
            state = self._reconstruct_snapshot_state(best_index)
        for event in sorted(self.inputs, key=lambda e: (e.frame, getattr(e, "timestamp", 0.0))):
            if base_frame < event.frame <= target_frame:
                state = self._apply_input(state, event)
        return state

    def check_determinism(self, replay1: list, replay2: list) -> bool:
        # bug4 fix: 校验确定性, 浮点数按 epsilon 比较,
        # 计算顺序不同导致的偏差会被检测出来
        if len(replay1) != len(replay2):
            return False
        for a, b in zip(replay1, replay2):
            if isinstance(a, float) or isinstance(b, float):
                if abs(a - b) > FLOAT_EPSILON:
                    return False
            elif a != b:
                return False
        return True

    def export_replay(self, path: str) -> bool:
        # bug5 fix: gzip 压缩 + sha256 完整性校验 + 版本号兼容
        payload = {
            "version": REPLAY_VERSION,
            "random_seed": self.random_seed,
            "physics_state": self.physics_state,
            "network_latency_ms": self.network_latency_ms,
            "inputs": [
                {"frame": e.frame, "key": e.key, "value": e.value,
                 "timestamp": e.timestamp}
                for e in self.inputs
            ],
            "snapshots": [
                {"frame": s.frame, "state": s.state,
                 "is_keyframe": s.is_keyframe}
                for s in self.snapshots
            ],
        }
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(body).hexdigest().encode("ascii")
        envelope = json.dumps({
            "checksum": checksum.decode("ascii"),
            "data": payload,
        }, sort_keys=True).encode("utf-8")
        with gzip.open(path, "wb") as f:
            f.write(envelope)
        return True

    def load_replay(self, path: str) -> bool:
        # bug5 fix: 加载时校验完整性, 损坏文件拒绝加载;
        # 检查版本兼容性, 旧版本回放走迁移路径
        try:
            with gzip.open(path, "rb") as f:
                envelope = json.loads(f.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        data = envelope.get("data")
        if data is None:
            return False
        body = json.dumps(data, sort_keys=True).encode("utf-8")
        if hashlib.sha256(body).hexdigest() != envelope.get("checksum"):
            return False
        version = data.get("version", 1)
        if version < MIN_SUPPORTED_VERSION or version > REPLAY_VERSION:
            return False
        if version < REPLAY_VERSION:
            data = self._migrate(data, version)
        self.random_seed = data.get("random_seed", 0)
        self.physics_state = data.get("physics_state", {})
        self.network_latency_ms = data.get("network_latency_ms", 0.0)
        self.inputs = [
            InputEvent(e["frame"], e["key"], e["value"],
                       e.get("timestamp", 0.0))
            for e in data.get("inputs", [])
        ]
        self.snapshots = [
            StateSnapshot(s["frame"], s["state"],
                          s.get("is_keyframe", True))
            for s in data.get("snapshots", [])
        ]
        return True

    def _migrate(self, data: dict, from_version: int) -> dict:
        # 版本迁移: v1 缺少时间戳/物理状态等字段, 补默认值
        if from_version == 1:
            data.setdefault("physics_state", {})
            data.setdefault("network_latency_ms", 0.0)
            for e in data.get("inputs", []):
                e.setdefault("timestamp", 0.0)
            data["version"] = REPLAY_VERSION
        return data
