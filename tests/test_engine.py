"""录像测试"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import ReplaySystem, ReplayFrame

class TestRecord:
    def test_records_seed(self):
        rs = ReplaySystem()
        rs.random_seed = 12345
        assert rs.get_seed() == 12345, "未记录随机种子"

class TestShare:
    def test_share_has_password(self):
        rs = ReplaySystem()
        link = rs.share("r1", password="secret")
        assert "secret" in link or link != "share_r1", "分享无权限控制"
