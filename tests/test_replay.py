"""回放/录像系统 - 红态测试"""
import pytest, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from replay.system import ReplaySystem

class TestInputTimestamp:
    def test_input_has_timestamp(self):
        rs = ReplaySystem()
        rs.record_input("attack", 1.0, 100)
        assert rs.inputs[0].frame == 100

class TestSnapshotDelta:
    def test_snapshot_uses_delta(self):
        rs = ReplaySystem()
        rs.take_snapshot(0, {"hp": 100})
        rs.take_snapshot(1, {"hp": 90})
        assert len(rs.snapshots) == 2

class TestSeekRecalculates:
    def test_seek_recalculates_state(self):
        rs = ReplaySystem()
        rs.snapshots.append(type("S",(),{"frame":0,"state":{"hp":100}})())
        rs.inputs.append(type("I",(),{"frame":5,"key":"hit","value":10})())
        result = rs.seek_replay(10)
        assert result.get("hp") == 90

class TestDeterminism:
    def test_determinism_checks_floats(self):
        rs = ReplaySystem()
        assert rs.check_determinism([1.0], [1.0000001]) == False

class TestExportCompression:
    def test_export_validates_integrity(self):
        rs = ReplaySystem()
        result = rs.export_replay("/tmp/test.replay")
        assert result == True
