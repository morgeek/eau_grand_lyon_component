"""Tests for EauGrandLyonCoordinator instance methods."""
from unittest.mock import MagicMock, patch
import pytest

from custom_components.eau_grand_lyon.coordinator import EauGrandLyonCoordinator


def _make_coordinator(options=None):
    """Build a minimal coordinator with no real HA wiring."""
    entry = MagicMock()
    entry.options = options or {}
    hass = MagicMock()
    hass.data = {}
    coord = EauGrandLyonCoordinator.__new__(EauGrandLyonCoordinator)
    coord._entry = entry
    coord.data = None
    coord._cumulative_index_cache = {}
    coord.logger = MagicMock()
    return coord


class TestCalculateDailyAggregates:
    def setup_method(self):
        self.coord = _make_coordinator()

    def test_empty_returns_none_none(self):
        assert self.coord._calculate_daily_aggregates([]) == (None, None)

    def test_fewer_than_7_uses_all(self):
        daily = [{"consommation_m3": 1.0} for _ in range(5)]
        c7, c30 = self.coord._calculate_daily_aggregates(daily)
        assert c7 == 5.0
        assert c30 == 5.0

    def test_7_days_correct(self, sample_daily):
        c7, c30 = self.coord._calculate_daily_aggregates(sample_daily)
        expected_7 = round(sum(e["consommation_m3"] for e in sample_daily[-7:]), 2)
        expected_30 = round(sum(e["consommation_m3"] for e in sample_daily[-30:]), 2)
        assert c7 == expected_7
        assert c30 == expected_30

    def test_30_days_same_as_7_when_only_7_entries(self):
        daily = [{"consommation_m3": 2.0} for _ in range(7)]
        c7, c30 = self.coord._calculate_daily_aggregates(daily)
        assert c7 == c30 == 14.0


class TestGetCumulativeIndex:
    def setup_method(self):
        self.coord = _make_coordinator()

    def test_no_data_returns_none(self):
        self.coord.data = None
        assert self.coord.get_cumulative_index("REF1") is None

    def test_real_index_used_when_present(self):
        self.coord.data = {
            "contracts": {"REF1": {"real_index": 1234.567, "consommations": []}}
        }
        assert self.coord.get_cumulative_index("REF1") == 1234.6

    def test_sum_used_when_no_real_index(self, sample_consos):
        self.coord.data = {
            "contracts": {"REF1": {"consommations": sample_consos}}
        }
        expected = round(sum(e["consommation_m3"] for e in sample_consos), 1)
        assert self.coord.get_cumulative_index("REF1") == expected

    def test_empty_consos_returns_none(self):
        self.coord.data = {"contracts": {"REF1": {"consommations": []}}}
        assert self.coord.get_cumulative_index("REF1") is None

    def test_cache_hit_avoids_recompute(self, sample_consos):
        self.coord.data = {
            "contracts": {"REF1": {"consommations": sample_consos}}
        }
        first = self.coord.get_cumulative_index("REF1")
        # Corrupt the underlying data — cache should still return first value
        self.coord.data["contracts"]["REF1"]["consommations"] = []
        assert self.coord.get_cumulative_index("REF1") == first

    def test_unknown_contract_returns_none(self):
        self.coord.data = {"contracts": {}}
        assert self.coord.get_cumulative_index("MISSING") is None
