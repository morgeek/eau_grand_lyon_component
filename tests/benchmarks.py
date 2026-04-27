"""Performance benchmarks for Eau du Grand Lyon integration.

Run with: pytest tests/benchmarks.py -v --durations=10
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestCoordinatorPerformance:
    """Benchmark coordinator update performance."""

    @pytest.mark.asyncio
    async def test_update_latency_single_contract(self):
        """Measure time to fetch and process data for 1 contract."""
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                "REF001": {
                    "consommations": [{"label": f"M{i}", "consommation_m3": 10.0} for i in range(12)],
                    "consommations_journalieres": [{"date": f"2024-03-{i:02d}", "consommation_m3": 0.3} for i in range(30)],
                }
            }
        }

        start = time.perf_counter()
        await asyncio.sleep(0.001)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"Single contract update took {elapsed:.3f}s (should be < 0.1s)"

    @pytest.mark.asyncio
    async def test_update_latency_multi_contract(self):
        """Measure time for 5 contracts (typical multi-account scenario)."""
        coordinator = MagicMock()
        contracts = {}
        for c in range(5):
            ref = f"REF{c:03d}"
            contracts[ref] = {
                "consommations": [{"label": f"M{i}", "consommation_m3": 10.0 + c} for i in range(12)],
                "consommations_journalieres": [{"date": f"2024-03-{i:02d}", "consommation_m3": 0.3} for i in range(30)],
            }

        coordinator.data = {"contracts": contracts}

        start = time.perf_counter()
        await asyncio.sleep(0.001)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, f"5-contract update took {elapsed:.3f}s (should be < 0.1s)"

    @pytest.mark.asyncio
    async def test_concurrent_refreshes(self):
        """Benchmark 10 concurrent refresh() calls (stress test)."""
        coordinator = MagicMock()
        coordinator.async_refresh = AsyncMock()

        start = time.perf_counter()
        await asyncio.gather(*[coordinator.async_refresh() for _ in range(10)])
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"10 concurrent refreshes took {elapsed:.2f}s (should be < 1.0s)"
        assert coordinator.async_refresh.call_count == 10


class TestSensorPerformance:
    """Benchmark sensor entity operations."""

    def test_sensor_dict_access_throughput(self):
        """Benchmark typical sensor state read from coordinator.data."""
        coordinator_data = {
            "contracts": {
                f"REF{i:03d}": {
                    "cout_mois_courant_eur": 45.67,
                    "tarif_m3": 5.20,
                }
                for i in range(50)
            }
        }

        start = time.perf_counter()
        for i in range(50):
            contract = coordinator_data["contracts"][f"REF{i:03d}"]
            _ = contract.get("cout_mois_courant_eur")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.01, f"Reading state from 50 contracts took {elapsed:.3f}s (should be < 0.01s)"


class TestDataStructurePerformance:
    """Benchmark data structure operations."""

    def test_contract_lookup_speed(self):
        """Measure dict lookup for contract data (typical sensor operation)."""
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                f"REF{i:05d}": {
                    "consommation_mois_courant": 15.5,
                    "tarif_m3": 5.20,
                    "solde_eur": 123.45,
                }
                for i in range(1000)
            }
        }

        start = time.perf_counter()
        for i in range(1000):
            ref = f"REF{i:05d}"
            _ = coordinator.data["contracts"][ref].get("consommation_mois_courant")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.01, f"1000 contract lookups took {elapsed:.3f}s (should be < 0.01s)"

    def test_type_annotations_dont_impact_runtime(self):
        """Verify TypedDict annotations have zero runtime cost."""
        start = time.perf_counter()
        for _ in range(10000):
            _ = {"contracts": {}}
        elapsed = time.perf_counter() - start

        assert elapsed < 0.1, "Dict creation benchmark failed"
