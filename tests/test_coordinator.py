"""Tests pour EauGrandLyonCoordinator et helpers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from custom_components.eau_grand_lyon.coordinator import (
    EauGrandLyonCoordinator,
    _find_missing_months,
)
from custom_components.eau_grand_lyon.api import (
    WafBlockedError,
    NetworkError,
    AuthenticationError,
    ApiError,
)


# ── Factories ─────────────────────────────────────────────────────────────────

def _make_entry(experimental: bool = False, tarif: float = 1.5, interval: int = 24):
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data     = {"email": "test@example.com", "password": "testpass", "tarif_m3": tarif}
    entry.options  = {
        "update_interval_hours": interval,
        "tarif_m3": tarif,
        "experimental_api": experimental,
    }
    return entry


def _make_coordinator(experimental: bool = False, tarif: float = 1.5) -> EauGrandLyonCoordinator:
    hass  = MagicMock()
    hass.async_create_task = MagicMock()
    entry = _make_entry(experimental=experimental, tarif=tarif)

    with patch("aiohttp.ClientSession"), patch("aiohttp.CookieJar"):
        coord = EauGrandLyonCoordinator(hass, entry)

    store            = MagicMock()
    store.async_load = AsyncMock(return_value=None)
    store.async_save = AsyncMock()
    coord._store     = store
    coord._entry     = entry
    return coord


_RAW_CONTRACT = {
    "id":        "C001",
    "reference": "REF123",
    "statutExtrait":    {"libelle": "Actif"},
    "dateEffet":        "2020-01-01T00:00:00Z",
    "dateEcheance":     "2025-01-01T00:00:00Z",
    "conditionPaiement": {
        "mensualise": False, "modePaiement": {"libelle": "Virement"},
        "compteClient": {"solde": {"value": 10.5}},
    },
    "servicesSouscrits": [{"calibreCompteur": {"libelle": "15"}, "usage": {"libelle": "Dom"}, "nombreHabitants": {}}],
    "espaceDeLivraison": {"reference": "PDS001"},
    "pointDeReleve": {"compteur": {}, "moduleRadio": {}},
}

_RAW_MONTHLY = [
    {"annee": 2024, "mois": 1, "consommation": 15.0},
    {"annee": 2024, "mois": 2, "consommation": 12.0},
    {"annee": 2024, "mois": 3, "consommation": 18.0},
]

_RAW_DAILY = [
    {"date": "2024-03-01", "consommation": 0.6},
    {"date": "2024-03-02", "consommation": 0.5},
    {"date": "2024-03-03", "consommation": 0.7},
]


# ── Tests _find_missing_months ────────────────────────────────────────────────

class TestFindMissingMonths:
    def test_no_missing_when_consecutive(self):
        consos = [
            {"annee": 2024, "mois_index": 0},
            {"annee": 2024, "mois_index": 1},
            {"annee": 2024, "mois_index": 2},
        ]
        assert _find_missing_months(consos) == []

    def test_detects_single_missing_month(self):
        consos = [
            {"annee": 2024, "mois_index": 0},
            {"annee": 2024, "mois_index": 2},  # mois 1 manquant
        ]
        result = _find_missing_months(consos)
        assert len(result) == 1
        assert "2024" in result[0]

    def test_detects_gap_across_year_boundary(self):
        consos = [
            {"annee": 2023, "mois_index": 11},  # Décembre 2023
            {"annee": 2024, "mois_index": 1},   # Février 2024 (janvier manquant)
        ]
        assert len(_find_missing_months(consos)) == 1

    def test_multiple_missing(self):
        consos = [
            {"annee": 2024, "mois_index": 0},
            {"annee": 2024, "mois_index": 4},  # 3 manquants : 1, 2, 3
        ]
        assert len(_find_missing_months(consos)) == 3

    def test_empty_returns_empty(self):
        assert _find_missing_months([]) == []

    def test_single_entry_returns_empty(self):
        assert _find_missing_months([{"annee": 2024, "mois_index": 0}]) == []


# ── Tests _fetch_all_data ─────────────────────────────────────────────────────

class TestFetchAllData:

    def _setup(self, coordinator, daily=None, monthly=None, experimental=False):
        """Configure les mocks API sur un coordinateur."""
        coordinator.api.get_contracts           = AsyncMock(return_value=[_RAW_CONTRACT])
        coordinator.api.get_alertes             = AsyncMock(return_value=[])
        coordinator.api.get_monthly_consumptions = AsyncMock(
            return_value=monthly if monthly is not None else _RAW_MONTHLY
        )
        coordinator.api.get_daily_consumptions   = AsyncMock(
            return_value=daily if daily is not None else _RAW_DAILY
        )
        if experimental:
            coordinator.api.get_factures         = AsyncMock(return_value=[])
            coordinator.api.get_courbe_de_charge = AsyncMock(return_value=[])
        coordinator._inject_statistics         = AsyncMock()
        coordinator._handle_alert_notifications = MagicMock()

    @pytest.mark.asyncio
    async def test_basic_legacy_returns_contracts(self):
        coord = _make_coordinator()
        self._setup(coord)
        data = await coord._fetch_all_data()
        assert "REF123" in data["contracts"]
        assert data["experimental_mode"] is False

    @pytest.mark.asyncio
    async def test_nb_alertes_propagated(self):
        coord = _make_coordinator()
        self._setup(coord)
        coord.api.get_alertes = AsyncMock(return_value=[{"id": "A1"}, {"id": "A2"}])
        data = await coord._fetch_all_data()
        assert data["nb_alertes"] == 2

    @pytest.mark.asyncio
    async def test_conso_7j_and_30j_computed(self):
        coord = _make_coordinator()
        daily = [{"date": f"2024-03-{d:02d}", "consommation": 1.0} for d in range(1, 32)]
        self._setup(coord, daily=daily)
        data = await coord._fetch_all_data()
        c = data["contracts"]["REF123"]
        assert c["consommation_7j"]  == pytest.approx(7.0)
        assert c["consommation_30j"] == pytest.approx(30.0)

    @pytest.mark.asyncio
    async def test_conso_7j_none_when_no_daily(self):
        coord = _make_coordinator()
        self._setup(coord, daily=[])
        data = await coord._fetch_all_data()
        c = data["contracts"]["REF123"]
        assert c["consommation_7j"]  is None
        assert c["consommation_30j"] is None

    @pytest.mark.asyncio
    async def test_cout_mois_computed_from_tarif(self):
        coord = _make_coordinator(tarif=2.0)
        self._setup(coord, monthly=[{"annee": 2024, "mois": 3, "consommation": 10.0}])
        data = await coord._fetch_all_data()
        # 10 m³ × 2.0 €/m³ = 20 €
        assert data["contracts"]["REF123"]["cout_mois_courant_eur"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_contract_without_reference_is_skipped(self):
        coord = _make_coordinator()
        bad_contract = {**_RAW_CONTRACT, "reference": ""}
        coord.api.get_contracts           = AsyncMock(return_value=[bad_contract])
        coord.api.get_alertes             = AsyncMock(return_value=[])
        coord.api.get_monthly_consumptions = AsyncMock(return_value=[])
        coord.api.get_daily_consumptions   = AsyncMock(return_value=[])
        coord._inject_statistics          = AsyncMock()
        coord._handle_alert_notifications  = MagicMock()
        data = await coord._fetch_all_data()
        assert data["contracts"] == {}

    @pytest.mark.asyncio
    async def test_no_contracts_returns_empty(self):
        coord = _make_coordinator()
        coord.api.get_contracts           = AsyncMock(return_value=[])
        coord.api.get_alertes             = AsyncMock(return_value=[])
        coord._inject_statistics          = AsyncMock()
        coord._handle_alert_notifications  = MagicMock()
        data = await coord._fetch_all_data()
        assert data["contracts"] == {}

    @pytest.mark.asyncio
    async def test_experimental_flag_in_data(self):
        coord = _make_coordinator(experimental=True)
        # _experimental est l'attribut interne de la property read-only
        coord.api._experimental = True
        self._setup(coord, experimental=True)
        data = await coord._fetch_all_data()
        assert data["experimental_mode"] is True

    @pytest.mark.asyncio
    async def test_experimental_fetches_factures(self):
        coord = _make_coordinator(experimental=True)
        coord.api._experimental = True
        facture_raw = {
            "reference": "F001", "dateEdition": "2024-03-01T00:00:00Z",
            "dateExigibilite": "2024-04-01", "montantHT": 30.0,
            "montantTTC": 35.0, "volume": 15.0,
            "statutPaiement": {"libelle": "Payée"}, "contrat": {"id": "C001"},
        }
        self._setup(coord, experimental=True)
        coord.api.get_factures = AsyncMock(return_value=[facture_raw])
        data = await coord._fetch_all_data()
        c = data["contracts"]["REF123"]
        assert c["derniere_facture"] is not None
        assert c["derniere_facture"]["contrat_id"] == "C001"

    @pytest.mark.asyncio
    async def test_experimental_fuite_estime_summed_over_30j(self):
        coord = _make_coordinator(experimental=True)
        coord.api._experimental = True
        daily = [
            {"date": f"2024-03-{d:02d}", "consommation": 0.5, "volumeFuiteEstime": 0.01}
            for d in range(1, 31)
        ]
        self._setup(coord, daily=daily, experimental=True)
        data = await coord._fetch_all_data()
        fuite = data["contracts"]["REF123"]["fuite_estime_30j_m3"]
        assert fuite == pytest.approx(0.3, abs=1e-3)

    @pytest.mark.asyncio
    async def test_experimental_no_courbe_when_no_daily(self):
        """Sans données journalières, get_courbe_de_charge ne doit pas être appelé."""
        coord = _make_coordinator(experimental=True)
        coord.api._experimental = True
        self._setup(coord, daily=[], experimental=True)
        data = await coord._fetch_all_data()
        coord.api.get_courbe_de_charge.assert_not_called()
        assert data["contracts"]["REF123"]["fuite_estime_30j_m3"] is None


# ── Tests mode hors-ligne ─────────────────────────────────────────────────────

class TestOfflineMode:

    @pytest.mark.asyncio
    async def test_offline_activated_after_3_waf_failures(self):
        coord = _make_coordinator()
        coord._last_good_data = {
            "contracts": {"REF123": {}},
            "nb_alertes": 0,
            "last_update_success_time": datetime.now(timezone.utc),
        }
        coord._last_request_mono = None
        coord._min_request_delay_s = 0
        coord._fetch_all_data = AsyncMock(side_effect=WafBlockedError("blocked"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            data = await coord._async_update_data()
        assert data["offline_mode"] is True
        assert data["last_error_type"] == "WafBlockedError"

    @pytest.mark.asyncio
    async def test_offline_activated_after_3_network_failures(self):
        coord = _make_coordinator()
        coord._last_good_data = {
            "contracts": {"REF123": {}},
            "nb_alertes": 0,
            "last_update_success_time": datetime.now(timezone.utc),
        }
        coord._last_request_mono = None
        coord._min_request_delay_s = 0
        coord._fetch_all_data = AsyncMock(side_effect=NetworkError("timeout"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            data = await coord._async_update_data()
        assert data["offline_mode"] is True
        assert data["last_error_type"] == "NetworkError"

    @pytest.mark.asyncio
    async def test_no_cache_raises_update_failed(self):
        from homeassistant.helpers.update_coordinator import UpdateFailed
        coord = _make_coordinator()
        coord._last_good_data = None
        coord._last_request_mono = None
        coord._min_request_delay_s = 0
        coord._fetch_all_data = AsyncMock(side_effect=NetworkError("timeout"))
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(UpdateFailed):
                await coord._async_update_data()

    @pytest.mark.asyncio
    async def test_auth_error_raises_immediately_without_retry(self):
        from homeassistant.helpers.update_coordinator import UpdateFailed
        coord = _make_coordinator()
        coord._last_good_data = None
        coord._last_request_mono = None
        coord._min_request_delay_s = 0
        coord._fetch_all_data = AsyncMock(side_effect=AuthenticationError("bad creds"))
        with pytest.raises(UpdateFailed, match="authentification"):
            await coord._async_update_data()
        # Doit avoir été appelé UNE seule fois (pas de retry)
        assert coord._fetch_all_data.call_count == 1

    @pytest.mark.asyncio
    async def test_success_clears_offline_state(self):
        coord = _make_coordinator()
        coord._last_request_mono = None
        coord._min_request_delay_s = 0
        now = datetime.now(timezone.utc)
        coord._fetch_all_data = AsyncMock(return_value={
            "contracts": {"REF123": {}}, "nb_alertes": 0,
        })
        coord._store.async_save = AsyncMock()
        data = await coord._async_update_data()
        assert data["offline_mode"] is False
        assert data["last_error"] is None


# ── Tests persistent data ─────────────────────────────────────────────────────

class TestPersistentData:

    @pytest.mark.asyncio
    async def test_save_serializes_datetime_to_iso(self):
        coord = _make_coordinator()
        now   = datetime.now(timezone.utc)
        coord._last_good_data = {
            "contracts": {},
            "nb_alertes": 0,
            "last_update_success_time": now,
            "offline_mode": False,
            "offline_since": None,
        }
        await coord._save_persistent_data()
        saved = coord._store.async_save.call_args[0][0]
        assert isinstance(saved["last_update_success_time"], str)

    @pytest.mark.asyncio
    async def test_load_parses_iso_string_to_datetime(self):
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value={
            "contracts": {"REF123": {}},
            "nb_alertes": 0,
            "last_update_success_time": "2024-01-15T10:00:00+00:00",
        })
        await coord._load_persistent_data()
        assert isinstance(coord.data["last_update_success_time"], datetime)

    @pytest.mark.asyncio
    async def test_load_empty_store_leaves_data_none(self):
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value=None)
        await coord._load_persistent_data()
        assert coord.data is None

    @pytest.mark.asyncio
    async def test_load_sets_offline_false(self):
        """Un cache chargé depuis le disque ne met pas le mode offline à True."""
        coord = _make_coordinator()
        coord._store.async_load = AsyncMock(return_value={
            "contracts": {"REF123": {}},
            "offline_mode": True,   # sauvegardé dans un état transitoire
            "last_update_success_time": "2024-01-15T10:00:00+00:00",
        })
        await coord._load_persistent_data()
        assert coord.data["offline_mode"] is False
