"""录像回放 - 带4个bug"""
from dataclasses import dataclass, field

@dataclass
class ReplayFrame:
    frame: int
    inputs: dict
    state: dict

class ReplaySystem:
    def __init__(self):
        self.frames: list[ReplayFrame] = []
        self.random_seed = None  # bug1: 不记录种子
        self.key_frames = set()

    def record_frame(self, frame_num, inputs, state):
        # bug2: 不压缩，全量存
        self.frames.append(ReplayFrame(frame_num, inputs, state))

    def fast_forward(self, target_frame):
        # bug3: 简单跳帧
        result = []
        for f in self.frames:
            if f.frame >= target_frame:
                result.append(f)
        return result

    def share(self, replay_id, password=None):
        # bug4: 无权限控制
        return f"share_{replay_id}"

    def get_seed(self):
        return self.random_seed
