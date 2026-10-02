"""回放/录像系统 - 含5个bug"""
from dataclasses import dataclass, field

@dataclass
class InputEvent:
    frame: int
    key: str
    value: float

@dataclass
class StateSnapshot:
    frame: int
    state: dict

class ReplaySystem:
    def __init__(self):
        self.inputs: list = []  # bug1: 无时间戳
        self.snapshots: list = []  # bug2: 全量保存
        self.random_seed: int = 0  # bug1: 不记录

    def record_input(self, key: str, value: float, frame: int) -> None:
        # bug1: 不记录时间戳和随机种子
        self.inputs.append(InputEvent(frame, key, value))

    def take_snapshot(self, frame: int, state: dict) -> None:
        # bug2: 全量保存，不做差分
        self.snapshots.append(StateSnapshot(frame, state))

    def seek_replay(self, target_frame: int) -> dict:
        # bug3: 不重新计算状态
        for snap in self.snapshots:
            if snap.frame == target_frame:
                return snap.state
        return {}

    def check_determinism(self, replay1: list, replay2: list) -> bool:
        # bug4: 不校验确定性
        return True

    def export_replay(self, path: str) -> bool:
        # bug5: 不压缩不校验
        return True
