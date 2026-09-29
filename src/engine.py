"""录像回放系统：确定性录制、增量压缩、关键帧快进、受控分享。"""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

KEY_EVENTS = ("skill", "kill", "death")


@dataclass
class ReplayFrame:
    frame: int
    inputs: dict
    state: dict  # 增量存储：仅相对上一帧发生变化的键


@dataclass
class ShareLink:
    replay_id: str
    token: str
    expires_at: float
    password_hash: str

    def url(self):
        return f"share_{self.replay_id}_{self.token}_exp{int(self.expires_at)}"


class ReplaySystem:
    def __init__(self):
        self.frames: list[ReplayFrame] = []
        self.random_seed = None
        self.initial_state: dict = {}
        self.key_frames = set()
        self._published: dict[str, bool] = {}
        self._shares: dict[str, ShareLink] = {}

    # ---- bug1 修复：记录随机种子与初始状态，保证回放确定性 ----
    def start_recording(self, seed, initial_state=None):
        self.random_seed = seed
        self.initial_state = dict(initial_state or {})
        self.frames.clear()
        self.key_frames.clear()

    def get_seed(self):
        return self.random_seed

    def get_initial_state(self):
        return dict(self.initial_state)

    # ---- bug2 修复：增量编码，只记录状态变化 ----
    def record_frame(self, frame_num, inputs, state, events=()):
        prev = self.state_at(self.frames[-1].frame) if self.frames else dict(self.initial_state)
        delta = {k: v for k, v in state.items() if prev.get(k) != v}
        self.frames.append(ReplayFrame(frame_num, dict(inputs), delta))
        if any(e in KEY_EVENTS for e in events):
            self.key_frames.add(frame_num)

    def state_at(self, frame_num):
        """由初始状态 + 增量回放重建任意帧的完整状态（确定性）。"""
        state = dict(self.initial_state)
        for f in self.frames:
            if f.frame > frame_num:
                break
            state.update(f.state)
        return state

    def compressed_size(self):
        return sum(len(f.state) for f in self.frames)

    # ---- bug3 修复：关键帧索引，事件帧在快进中必保留 ----
    def fast_forward(self, target_frame):
        result = []
        for f in self.frames:
            if f.frame >= target_frame or f.frame in self.key_frames:
                result.append(f)
        return result

    # ---- bug4 修复：时效 + 密码 + 未公开内容禁止分享 ----
    def register_replay(self, replay_id, published=False):
        self._published[replay_id] = published

    def share(self, replay_id, password=None, ttl_seconds=3600):
        if not self._published.get(replay_id, False) and replay_id in self._published:
            raise PermissionError(f"录像 {replay_id} 未公开，禁止分享")
        token = secrets.token_hex(8)
        password_hash = (
            hashlib.sha256(password.encode()).hexdigest() if password else None
        )
        link = ShareLink(replay_id, token, time.time() + ttl_seconds, password_hash)
        self._shares[token] = link
        return link.url()

    def open_share(self, url, password=None):
        token = url.split("_")[2]
        link = self._shares.get(token)
        if link is None:
            raise PermissionError("分享链接无效")
        if time.time() > link.expires_at:
            raise PermissionError("分享链接已过期")
        if link.password_hash is not None:
            digest = hashlib.sha256(password.encode()).hexdigest() if password else None
            if not hmac.compare_digest(digest or "", link.password_hash):
                raise PermissionError("密码错误")
        return link.replay_id
