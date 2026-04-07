"""Tests for filters module."""

from datetime import datetime

from ci_optimizer.filters import AnalysisFilters


class TestAnalysisFilters:
    def test_default_empty(self):
        f = AnalysisFilters()
        assert f.time_range is None
        assert f.workflows is None
        assert f.status is None
        assert f.branches is None

    def test_to_dict_empty(self):
        f = AnalysisFilters()
        assert f.to_dict() == {}

    def test_to_dict_with_time_range(self):
        since = datetime(2024, 1, 1)
        until = datetime(2024, 3, 1)
        f = AnalysisFilters(time_range=(since, until))
        d = f.to_dict()
        assert "since" in d
        assert "until" in d
        assert d["since"] == since.isoformat()
        assert d["until"] == until.isoformat()

    def test_to_dict_with_all_fields(self):
        since = datetime(2024, 1, 1)
        until = datetime(2024, 6, 1)
        f = AnalysisFilters(
            time_range=(since, until),
            workflows=["ci.yml", "deploy.yml"],
            status=["failure"],
            branches=["main", "develop"],
        )
        d = f.to_dict()
        assert d["workflows"] == ["ci.yml", "deploy.yml"]
        assert d["status"] == ["failure"]
        assert d["branches"] == ["main", "develop"]

    def test_from_dict_empty(self):
        f = AnalysisFilters.from_dict({})
        assert f.time_range is None
        assert f.workflows is None

    def test_from_dict_full(self):
        data = {
            "since": "2024-01-01T00:00:00",
            "until": "2024-06-01T00:00:00",
            "workflows": ["ci.yml"],
            "status": ["failure", "success"],
            "branches": ["main"],
        }
        f = AnalysisFilters.from_dict(data)
        assert f.time_range is not None
        assert f.time_range[0] == datetime(2024, 1, 1)
        assert f.time_range[1] == datetime(2024, 6, 1)
        assert f.workflows == ["ci.yml"]
        assert f.status == ["failure", "success"]
        assert f.branches == ["main"]

    def test_roundtrip(self):
        original = AnalysisFilters(
            time_range=(datetime(2024, 1, 1), datetime(2024, 12, 31)),
            workflows=["ci.yml"],
            status=["failure"],
            branches=["main"],
        )
        restored = AnalysisFilters.from_dict(original.to_dict())
        assert restored.workflows == original.workflows
        assert restored.status == original.status
        assert restored.branches == original.branches
        assert restored.time_range is not None
        assert restored.time_range[0] == original.time_range[0]
        assert restored.time_range[1] == original.time_range[1]
