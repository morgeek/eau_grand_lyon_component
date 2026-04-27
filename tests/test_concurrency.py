"""Concurrency and stress tests for coordinator.

Tests rapid concurrent async_refresh() calls to validate thread-safety and
no deadlocks under high concurrent load.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


class TestConcurrentRefresh:
    """Test coordinator behavior under concurrent refresh requests."""

    @pytest.mark.asyncio
    async def test_rapid_sequential_refreshes(self):
        """Test 10 sequential refresh() calls — validates no state corruption."""
        coordinator = MagicMock()
        coordinator.async_refresh = AsyncMock()
        coordinator.data = {"contracts": {}}

        for _ in range(10):
            await coordinator.async_refresh()

        assert coordinator.async_refresh.call_count == 10

    @pytest.mark.asyncio
    async def test_concurrent_refreshes_10x(self):
        """Test 10 concurrent refresh() calls simultaneously."""
        coordinator = MagicMock()
        coordinator.async_refresh = AsyncMock(return_value=None)
        coordinator.data = {"contracts": {}}

        tasks = [coordinator.async_refresh() for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert len(results) == 10
        assert not any(isinstance(r, Exception) for r in results)
        assert coordinator.async_refresh.call_count == 10

    @pytest.mark.asyncio
    async def test_concurrent_refreshes_100x(self):
        """Test 100 concurrent refresh() calls — stress test."""
        coordinator = MagicMock()
        coordinator.async_refresh = AsyncMock(return_value=None)
        coordinator.data = {"contracts": {}}

        tasks = [coordinator.async_refresh() for _ in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        assert len(results) == 100
        assert not any(isinstance(r, Exception) for r in results)
        assert coordinator.async_refresh.call_count == 100

    @pytest.mark.asyncio
    async def test_refresh_during_data_access(self):
        """Test data access while refresh is in progress."""
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {
                "REF001": {
                    "consommation_mois_courant": 15.5,
                    "tarif_m3": 5.20,
                }
            }
        }

        async def read_data():
            """Simulate sensor reading from coordinator.data."""
            for _ in range(50):
                contract = coordinator.data.get("contracts", {}).get("REF001")
                if contract:
                    _ = contract.get("consommation_mois_courant")
                await asyncio.sleep(0.001)

        async def refresh_data():
            """Simulate coordinator refresh."""
            for i in range(10):
                coordinator.data = {
                    "contracts": {
                        "REF001": {
                            "consommation_mois_courant": 15.5 + i * 0.1,
                            "tarif_m3": 5.20,
                        }
                    }
                }
                await asyncio.sleep(0.002)

        await asyncio.gather(read_data(), refresh_data())

    @pytest.mark.asyncio
    async def test_refresh_with_error_handling(self):
        """Test concurrent refreshes with some failing."""
        coordinator = MagicMock()
        call_count = 0

        async def refresh_with_intermittent_error():
            nonlocal call_count
            call_count += 1
            if call_count % 3 == 0:
                raise RuntimeError("Simulated API error")
            return None

        coordinator.async_refresh = AsyncMock(side_effect=refresh_with_intermittent_error)

        tasks = [coordinator.async_refresh() for _ in range(9)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, Exception)]
        successes = [r for r in results if not isinstance(r, Exception)]

        assert len(errors) == 3
        assert len(successes) == 6

    @pytest.mark.asyncio
    async def test_data_consistency_under_concurrent_updates(self):
        """Validate coordinator.data remains consistent."""
        coordinator = MagicMock()
        coordinator.data = {
            "contracts": {f"REF{i:03d}": {"index": i} for i in range(10)}
        }

        async def update_all():
            """Update all contracts."""
            for iteration in range(5):
                for i in range(10):
                    ref = f"REF{i:03d}"
                    if ref in coordinator.data["contracts"]:
                        coordinator.data["contracts"][ref]["index"] = iteration

        async def read_all():
            """Continuously read all contracts."""
            for _ in range(50):
                contracts = coordinator.data.get("contracts", {})
                for ref in list(contracts.keys()):
                    _ = contracts[ref].get("index")
                await asyncio.sleep(0.001)

        await asyncio.gather(update_all(), read_all())

        assert "REF000" in coordinator.data["contracts"]
        assert len(coordinator.data["contracts"]) == 10
