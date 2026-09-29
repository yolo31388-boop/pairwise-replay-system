"""录像回放系统：确定性回放、增量压缩、关键帧快进、受控分享。"""
import hashlib
import hmac
import json
import time
import zlib
from dataclasses import dataclass

# 必须保留为关键帧的事件类型
KEY_EVENTS = ("skill_cast", "kill", "death")


@dataclass
class ReplayFrame:
    frame: int
    inputs: dict
    state: dict  # 增量编码：仅存放相对上一帧变化的键
    is_keyframe: bool = False


@dataclass
class ShareLink:
    replay_id: str
    token: str
    expires_at: float
    url: str


class ReplaySystem:
    def __init__(self):
        self.frames = []
        self.random_seed = None
        self.initial_state = {}
        self.key_frames = set()
        self.events = []
        self._shares = {}
        self._passwords = {}
        self._restricted = set()  # 未公开内容（如新英雄实战）禁止分享
        self._secret = b"replay-system"

    # ---- bug1 修复：记录种子与初始状态，保证回放确定性 ----
    def start_recording(self, seed, initial_state):
        self.random_seed = seed
        self.initial_state = dict(initial_state)
        self.frames.clear()
        self.key_frames.clear()
        self.events.clear()

    def get_seed(self):
        return self.random_seed

    def get_initial_state(self):
        return dict(self.initial_state)

    # ---- bug2 修复：增量编码，只记录状态变化 ----
    def record_frame(self, frame_num, inputs, state):
        if self.frames:
            prev = self.get_state_at(len(self.frames) - 1)
        else:
            prev = dict(self.initial_state)
        is_key = frame_num in self.key_frames or not self.frames
        if is_key:
            delta = dict(state)  # 关键帧存全量，便于快进定位
        else:
            delta = {k: v for k, v in state.items() if prev.get(k) != v}
        self.frames.append(ReplayFrame(frame_num, dict(inputs), delta, is_key))

    def get_state_at(self, index):
        state = dict(self.initial_state)
        for f in self.frames[: index + 1]:
            state.update(f.state)
        return state

    def serialize(self):
        payload = json.dumps({
            "seed": self.random_seed,
            "initial_state": self.initial_state,
            "frames": [
                {"frame": f.frame, "inputs": f.inputs,
                 "state": f.state, "key": f.is_keyframe}
                for f in self.frames
            ],
        }).encode()
        return zlib.compress(payload, 9)

    # ---- bug3 修复：关键帧索引，事件帧快进时不跳过 ----
    def record_event(self, frame_num, event_type, data=None):
        self.events.append((frame_num, event_type, data or {}))
        if event_type in KEY_EVENTS:
            self.key_frames.add(frame_num)
            for i, f in enumerate(self.frames):
                if f.frame == frame_num:
                    f.is_keyframe = True
                    f.state = self.get_state_at(i)  # 提升为全量关键帧

    def fast_forward(self, target_frame):
        # 目标帧之前的技能/击杀/死亡等关键帧必须保留
        result = [f for f in self.frames if f.is_keyframe and f.frame <= target_frame]
        result.extend(f for f in self.frames
                      if f.frame >= target_frame and not f.is_keyframe)
        result.sort(key=lambda f: f.frame)
        return result

    # ---- bug4 修复：分享带时效和密码，未公开内容禁止分享 ----
    def restrict(self, replay_id):
        """标记为未公开内容，禁止生成分享链接。"""
        self._restricted.add(replay_id)

    def publish(self, replay_id):
        self._restricted.discard(replay_id)

    def share(self, replay_id, password=None, expires_in=3600):
        if replay_id in self._restricted:
            raise PermissionError(f"录像 {replay_id} 未公开，禁止分享")
        expires_at = time.time() + expires_in
        token = hmac.new(
            self._secret, f"{replay_id}:{expires_at}".encode(), hashlib.sha256
        ).hexdigest()[:16]
        link = ShareLink(replay_id, token, expires_at,
                         f"share_{replay_id}?token={token}&expires={int(expires_at)}")
        self._shares[token] = link
        if password is not None:
            self._passwords[token] = hashlib.sha256(password.encode()).hexdigest()
        return link.url

    def open_share(self, url, password=None):
        token = url.split("token=")[1].split("&")[0]
        link = self._shares.get(token)
        if link is None:
            raise PermissionError("分享链接无效")
        if time.time() > link.expires_at:
            raise PermissionError("分享链接已过期")
        expected = self._passwords.get(token)
        if expected is not None:
            if password is None or hashlib.sha256(
                    password.encode()).hexdigest() != expected:
                raise PermissionError("密码错误")
        return link.replay_id
