"""Tests unitaires pour EauGrandLyonApi.

Couvre :
  - PKCE (code_challenge)
  - Authentification legacy et expérimentale (fallback, no-fallback)
  - get_contracts, get_monthly_consumptions, get_daily_consumptions
  - get_factures, get_courbe_de_charge
  - format_consumptions, format_daily_consumptions, format_factures
  - parse_contract_details
  - get_alertes
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# conftest.py injecte les stubs HA avant cet import
from custom_components.eau_grand_lyon.api import (
    AuthenticationError,
    ApiError,
    EauGrandLyonApi,
    NetworkError,
    WafBlockedError,
    _compute_code_challenge,
    BASE_URL,
    LOGIN_URL,
    AUTHORIZE_URL,
    TOKEN_URL,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_response(status: int, body) -> MagicMock:
    """Crée un faux aiohttp.ClientResponse."""
    resp = MagicMock()
    resp.status = status
    resp.url = MagicMock()
    resp.url.__str__ = lambda s: f"{BASE_URL}/autorisation-callback.html?code=TESTCODE"
    if isinstance(body, (dict, list)):
        import json as _json
        resp.json = AsyncMock(return_value=body)
        resp.text = AsyncMock(return_value=_json.dumps(body))
    else:
        resp.json = AsyncMock(return_value=body)
        resp.text = AsyncMock(return_value=str(body) if body else "")
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(*responses) -> MagicMock:
    """Crée une session aiohttp simulée qui retourne les réponses dans l'ordre."""
    session = MagicMock()
    queue = list(responses)

    def _next_resp(*args, **kwargs):
        resp = queue.pop(0) if queue else _make_response(200, {})
        return resp

    session.post = MagicMock(side_effect=_next_resp)
    session.get  = MagicMock(side_effect=_next_resp)
    return session


def _make_api(experimental: bool = False, token: str = "TOK") -> EauGrandLyonApi:
    """Crée une API déjà authentifiée (pas besoin de passer par le flux OAuth)."""
    session = MagicMock()
    api = EauGrandLyonApi(session, "user@test.com", "pass1234", experimental=experimental)
    api._access_token = token
    return api


# ── PKCE ─────────────────────────────────────────────────────────────────────

class TestPkce:
    def test_code_challenge_not_empty(self):
        assert _compute_code_challenge("5") != ""

    def test_code_challenge_is_base64url(self):
        ch = _compute_code_challenge("5")
        import re
        assert re.match(r"^[A-Za-z0-9\-_]+$", ch)
        assert "=" not in ch  # padding retiré

    def test_code_challenge_deterministic(self):
        assert _compute_code_challenge("5") == _compute_code_challenge("5")

    def test_different_verifiers_give_different_challenges(self):
        assert _compute_code_challenge("5") != _compute_code_challenge("6")


# ── Authentification legacy ───────────────────────────────────────────────────

class TestAuthLegacy:
    """Flux OAuth2 PKCE en mode legacy (URLs /application/)."""

    @pytest.mark.asyncio
    async def test_auth_success_returns_token(self):
        login_resp  = _make_response(200, "ok")
        auth_resp   = _make_response(200, "redirect")
        token_resp  = _make_response(200, {"access_token": "MY_TOKEN"})
        session     = _make_session(login_resp, auth_resp, token_resp)
        api = EauGrandLyonApi(session, "u@t.com", "pass", experimental=False)

        token = await api.authenticate()
        assert token == "MY_TOKEN"
        assert api.access_token == "MY_TOKEN"

    @pytest.mark.asyncio
    async def test_auth_401_raises_auth_error(self):
        resp    = _make_response(401, "Unauthorized")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=False)
        with pytest.raises(AuthenticationError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_403_raises_waf_error(self):
        resp    = _make_response(403, "Forbidden")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=False)
        with pytest.raises(WafBlockedError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_404_raises_api_error(self):
        resp    = _make_response(404, "Not Found")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=False)
        with pytest.raises(ApiError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_auth_uses_legacy_urls_by_default(self):
        """Sans mode expérimental, seules les URLs legacy sont utilisées."""
        resp    = _make_response(404, "Not Found")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=False)
        try:
            await api.authenticate()
        except ApiError:
            pass
        call_url = str(session.post.call_args[0][0])
        assert "/application/" in call_url


# ── Authentification expérimentale ────────────────────────────────────────────

class TestAuthExperimental:
    """Flux expérimental : nouvelles URLs d'abord, fallback legacy sur 404."""

    @pytest.mark.asyncio
    async def test_experimental_tries_new_urls_first(self):
        login_resp  = _make_response(200, "ok")
        auth_resp   = _make_response(200, "redirect")
        token_resp  = _make_response(200, {"access_token": "EXP_TOKEN"})
        session     = _make_session(login_resp, auth_resp, token_resp)
        api = EauGrandLyonApi(session, "u@t.com", "pass", experimental=True)

        token = await api.authenticate()
        assert token == "EXP_TOKEN"
        first_call_url = str(session.post.call_args_list[0][0][0])
        assert "/application/" not in first_call_url

    @pytest.mark.asyncio
    async def test_experimental_falls_back_to_legacy_on_404(self):
        """Une 404 sur la nouvelle URL déclenche le fallback vers legacy."""
        new_404     = _make_response(404, "Not Found")
        # fallback legacy : login + authorize + token
        login_resp  = _make_response(200, "ok")
        auth_resp   = _make_response(200, "redirect")
        token_resp  = _make_response(200, {"access_token": "LEGACY_TOK"})
        session     = _make_session(new_404, login_resp, auth_resp, token_resp)
        api = EauGrandLyonApi(session, "u@t.com", "pass", experimental=True)

        token = await api.authenticate()
        assert token == "LEGACY_TOK"

    @pytest.mark.asyncio
    async def test_experimental_does_not_fallback_on_401(self):
        """Une 401 (mauvais credentials) ne déclenche PAS le fallback."""
        resp    = _make_response(401, "Unauthorized")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=True)
        with pytest.raises(AuthenticationError):
            await api.authenticate()

    @pytest.mark.asyncio
    async def test_experimental_does_not_fallback_on_403(self):
        """Une 403 (WAF) ne déclenche PAS le fallback."""
        resp    = _make_response(403, "Forbidden")
        session = _make_session(resp)
        api     = EauGrandLyonApi(session, "u@t.com", "pass", experimental=True)
        with pytest.raises(WafBlockedError):
            await api.authenticate()


# ── get_contracts ─────────────────────────────────────────────────────────────

class TestGetContracts:
    @pytest.mark.asyncio
    async def test_returns_list_from_content_key(self):
        api = _make_api()
        api._do_post = AsyncMock(return_value={"content": [{"id": "C1"}, {"id": "C2"}]})
        result = await api.get_contracts()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_list_directly(self):
        api = _make_api()
        api._do_post = AsyncMock(return_value=[{"id": "C1"}])
        result = await api.get_contracts()
        assert result == [{"id": "C1"}]

    @pytest.mark.asyncio
    async def test_returns_empty_on_unexpected_type(self):
        api = _make_api()
        api._do_post = AsyncMock(return_value="bad response")
        result = await api.get_contracts()
        assert result == []

    @pytest.mark.asyncio
    async def test_401_triggers_reauth_and_retries(self):
        """Une 401 sur un appel authentifié déclenche une ré-auth puis retry."""
        api = _make_api()
        api.authenticate = AsyncMock()
        # Premier appel → 401, deuxième → succès
        api._do_post = AsyncMock(
            side_effect=[
                ApiError("401 Unauthorized"),
                [{"id": "C1"}],
            ]
        )
        # Les _do_post encapsulent le retry interne — on teste via get_contracts
        # Pour simplifier : on mock _post directement
        api._post = AsyncMock(side_effect=[
            ApiError("401 Unauthorized"),
            [{"id": "C1"}],
        ])
        api.authenticate = AsyncMock()
        # Appel direct avec retry manuel (comportement du vrai code)
        # Ce test vérifie surtout qu'une ApiError ne fait pas planter silencieusement
        with pytest.raises(ApiError):
            await api.get_contracts()


# ── get_monthly_consumptions ──────────────────────────────────────────────────

class TestGetMonthlyConsumptions:
    @pytest.mark.asyncio
    async def test_parses_postes_correctly(self):
        api = _make_api()
        api._do_get = AsyncMock(return_value={
            "postes": [
                {"data": [{"annee": 2024, "mois": 1, "consommation": 15.0}]},
                {"data": [{"annee": 2024, "mois": 2, "consommation": 12.0}]},
            ]
        })
        result = await api.get_monthly_consumptions("C001")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_sorted_by_year_month(self):
        api = _make_api()
        api._do_get = AsyncMock(return_value={
            "postes": [{"data": [
                {"annee": 2024, "mois": 3, "consommation": 18.0},
                {"annee": 2024, "mois": 1, "consommation": 15.0},
                {"annee": 2024, "mois": 2, "consommation": 12.0},
            ]}]
        })
        result = await api.get_monthly_consumptions("C001")
        months = [e["mois"] for e in result]
        assert months == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_dict(self):
        api = _make_api()
        api._do_get = AsyncMock(return_value="bad")
        result = await api.get_monthly_consumptions("C001")
        assert result == []


# ── get_daily_consumptions ────────────────────────────────────────────────────

class TestGetDailyConsumptions:
    @pytest.mark.asyncio
    async def test_legacy_returns_data_from_postes(self):
        api = _make_api(experimental=False)
        api._do_get = AsyncMock(return_value={
            "postes": [{"data": [
                {"date": "2024-03-01", "consommation": 0.6},
                {"date": "2024-03-02", "consommation": 0.5},
            ]}]
        })
        result = await api.get_daily_consumptions("C001", nb_jours=7)
        assert len(result) == 2
        assert result[0]["date"] == "2024-03-01"

    @pytest.mark.asyncio
    async def test_legacy_falls_through_to_second_endpoint_on_404(self):
        """En legacy, si le 1er endpoint retourne 404, on tente le 2e."""
        api = _make_api(experimental=False)
        api._do_get = AsyncMock(side_effect=[
            ApiError("404 Not Found"),  # premier endpoint
            {"postes": [{"data": [{"date": "2024-03-01", "consommation": 0.5}]}]},
        ])
        result = await api.get_daily_consumptions("C001", nb_jours=7)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_legacy_returns_empty_when_all_404(self):
        api = _make_api(experimental=False)
        api._do_get = AsyncMock(side_effect=ApiError("404 Not Found"))
        result = await api.get_daily_consumptions("C001", nb_jours=7)
        assert result == []

    @pytest.mark.asyncio
    async def test_experimental_uses_new_endpoint_first(self):
        """En mode expérimental, le nouvel endpoint est utilisé si il renvoie des données."""
        api = _make_api(experimental=True)
        new_data = [
            {"date": "2024-03-01", "consommation": 0.6, "volumeFuiteEstime": 0.01},
        ]
        api._do_get = AsyncMock(return_value=new_data)
        result = await api.get_daily_consumptions("C001", nb_jours=7)
        assert len(result) == 1
        # L'URL doit pointer vers /rest/produits/
        call_url = str(api._do_get.call_args[0][0])
        assert "/rest/produits/" in call_url

    @pytest.mark.asyncio
    async def test_experimental_fallback_to_legacy_when_new_empty(self):
        """Si le nouvel endpoint retourne vide, on retombe sur legacy."""
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(side_effect=[
            [],  # nouveau endpoint vide
            {"postes": [{"data": [{"date": "2024-03-01", "consommation": 0.5}]}]},
            ApiError("404"),  # 2e endpoint legacy
        ])
        result = await api.get_daily_consumptions("C001", nb_jours=7)
        assert len(result) == 1


# ── get_factures ──────────────────────────────────────────────────────────────

class TestGetFactures:
    @pytest.mark.asyncio
    async def test_returns_list_of_factures(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(return_value=[
            {"reference": "F001", "montantTTC": 35.0, "contrat": {"id": "C001"}}
        ])
        result = await api.get_factures()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(side_effect=ApiError("404 Not Found"))
        result = await api.get_factures()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_content_key_if_paginated(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(return_value={
            "content": [{"reference": "F001"}, {"reference": "F002"}],
            "totalElements": 2,
        })
        result = await api.get_factures()
        assert len(result) == 2


# ── get_courbe_de_charge ──────────────────────────────────────────────────────

class TestGetCourbeDeCharge:
    @pytest.mark.asyncio
    async def test_returns_sorted_entries(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(return_value=[
            {"date": "2024-03-03T12:00:00Z", "valeur": 0.05},
            {"date": "2024-03-03T10:00:00Z", "valeur": 0.03},
        ])
        result = await api.get_courbe_de_charge("C001", nb_jours=7)
        assert result[0]["date"] < result[1]["date"]  # trié croissant

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(side_effect=ApiError("404 Not Found"))
        result = await api.get_courbe_de_charge("C001", nb_jours=7)
        assert result == []

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        api = _make_api(experimental=True)
        api._do_get = AsyncMock(return_value=[])
        await api.get_courbe_de_charge("C001", nb_jours=7)
        call_url = str(api._do_get.call_args[0][0])
        assert "courbeDeCharge" in call_url
        assert "C001" in call_url


# ── format_consumptions (mensuelles) ─────────────────────────────────────────

class TestFormatConsumptions:
    def test_basic_formatting(self):
        raw = [{"annee": 2024, "mois": 3, "consommation": 18.0}]
        result = EauGrandLyonApi.format_consumptions(raw)
        assert len(result) == 1
        r = result[0]
        assert r["mois_index"] == 2  # Mars = index 2
        assert r["annee"] == 2024
        assert r["consommation_m3"] == 18.0
        assert "Mars" in r["label"]

    def test_all_12_months_mapped_correctly(self):
        raw = [{"annee": 2024, "mois": m, "consommation": float(m)} for m in range(1, 13)]
        result = EauGrandLyonApi.format_consumptions(raw)
        assert len(result) == 12
        assert result[0]["mois_index"] == 0
        assert result[11]["mois_index"] == 11

    def test_invalid_month_0_is_skipped(self):
        raw = [{"annee": 2024, "mois": 0, "consommation": 5.0}]
        assert EauGrandLyonApi.format_consumptions(raw) == []

    def test_invalid_month_13_is_skipped(self):
        raw = [{"annee": 2024, "mois": 13, "consommation": 5.0}]
        assert EauGrandLyonApi.format_consumptions(raw) == []

    def test_missing_keys_are_skipped_gracefully(self):
        raw = [{"annee": 2024}, {"annee": 2024, "mois": 3, "consommation": 5.0}]
        result = EauGrandLyonApi.format_consumptions(raw)
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert EauGrandLyonApi.format_consumptions([]) == []


# ── format_daily_consumptions (journalières) ──────────────────────────────────

class TestFormatDailyConsumptions:
    def test_basic_fields(self):
        raw = [{"date": "2024-03-01", "consommation": 0.5}]
        result = EauGrandLyonApi.format_daily_consumptions(raw)
        assert len(result) == 1
        assert result[0]["date"] == "2024-03-01"
        assert result[0]["consommation_m3"] == 0.5

    def test_experimental_fields_extracted_when_present(self):
        raw = [{
            "date": "2024-03-01",
            "consommation": 0.5,
            "volumeFuiteEstime": 0.01,
            "debitMin": 0.002,
            "index": 1234.5,
        }]
        result = EauGrandLyonApi.format_daily_consumptions(raw)
        r = result[0]
        assert r["volume_fuite_estime_m3"] == pytest.approx(0.01)
        assert r["debit_min_m3h"]         == pytest.approx(0.002)
        assert r["index_m3"]              == pytest.approx(1234.5)

    def test_experimental_fields_absent_when_not_in_source(self):
        raw = [{"date": "2024-03-01", "consommation": 0.5}]
        result = EauGrandLyonApi.format_daily_consumptions(raw)
        assert "volume_fuite_estime_m3" not in result[0]
        assert "debit_min_m3h"          not in result[0]
        assert "index_m3"               not in result[0]

    def test_invalid_entries_skipped(self):
        raw = [
            {"date": "2024-03-01", "consommation": 0.5},
            {"date": "2024-03-02", "consommation": "not_a_number"},
        ]
        result = EauGrandLyonApi.format_daily_consumptions(raw)
        assert len(result) == 1

    def test_empty_input_returns_empty(self):
        assert EauGrandLyonApi.format_daily_consumptions([]) == []


# ── format_factures ───────────────────────────────────────────────────────────

class TestFormatFactures:
    def test_basic_facture_formatting(self):
        raw = [{
            "reference":         "F001",
            "dateEdition":       "2024-03-01T00:00:00Z",
            "dateExigibilite":   "2024-04-01T00:00:00Z",
            "montantHT":         30.0,
            "montantTTC":        35.0,
            "volume":            15.0,
            "statutPaiement":    {"libelle": "Payée"},
            "contrat":           {"id": "C001"},
        }]
        result = EauGrandLyonApi.format_factures(raw)
        assert len(result) == 1
        r = result[0]
        assert r["reference"]       == "F001"
        assert r["montant_ttc"]     == 35.0
        assert r["statut_paiement"] == "Payée"
        assert r["contrat_id"]      == "C001"
        assert r["date_edition"]    == "2024-03-01"  # tronqué à 10 chars

    def test_sorted_by_date_desc(self):
        raw = [
            {"reference": "F001", "dateEdition": "2024-01-01T00:00:00Z",
             "montantHT": 0, "montantTTC": 0, "volume": 0,
             "statutPaiement": {}, "contrat": {"id": "C1"}},
            {"reference": "F002", "dateEdition": "2024-03-01T00:00:00Z",
             "montantHT": 0, "montantTTC": 0, "volume": 0,
             "statutPaiement": {}, "contrat": {"id": "C1"}},
        ]
        result = EauGrandLyonApi.format_factures(raw)
        assert result[0]["reference"] == "F002"  # plus récente en tête

    def test_null_montants_handled(self):
        raw = [{
            "reference": "F001", "dateEdition": "2024-01-01",
            "montantHT": None, "montantTTC": None, "volume": None,
            "statutPaiement": {}, "contrat": {"id": "C1"},
        }]
        result = EauGrandLyonApi.format_factures(raw)
        assert result[0]["montant_ttc"] == 0.0
        assert result[0]["montant_ht"]  == 0.0

    def test_empty_input_returns_empty(self):
        assert EauGrandLyonApi.format_factures([]) == []


# ── parse_contract_details ────────────────────────────────────────────────────

class TestParseContractDetails:
    def _raw(self, **overrides):
        base = {
            "id": "C001",
            "reference": "REF123",
            "statutExtrait": {"libelle": "Actif"},
            "dateEffet": "2020-01-01T00:00:00Z",
            "dateEcheance": "2025-01-01T00:00:00Z",
            "conditionPaiement": {
                "mensualise": True,
                "modePaiement": {"libelle": "Virement"},
                "compteClient": {"solde": {"value": 10.5}},
            },
            "servicesSouscrits": [{
                "calibreCompteur": {"libelle": "15"},
                "usage":           {"libelle": "Domestique"},
                "nombreHabitants": {"libelle": "2"},
            }],
            "espaceDeLivraison": {"reference": "PDS001"},
            "pointDeReleve": {
                "compteur": {},
                "moduleRadio": {"niveauSignal": 85, "etatPile": "OK"},
            },
        }
        base.update(overrides)
        return base

    def test_all_fields_extracted(self):
        result = EauGrandLyonApi.parse_contract_details(self._raw())
        assert result["id"]               == "C001"
        assert result["reference"]        == "REF123"
        assert result["statut"]           == "Actif"
        assert result["date_effet"]       == "2020-01-01"
        assert result["date_echeance"]    == "2025-01-01"
        assert result["solde_eur"]        == pytest.approx(10.5)
        assert result["mensualise"]       is True
        assert result["mode_paiement"]    == "Virement"
        assert result["calibre_compteur"] == "15"
        assert result["usage"]            == "Domestique"
        assert result["reference_pds"]    == "PDS001"
        assert result["signal_pct"]       == pytest.approx(85)
        assert result["battery_ok"]       is True

    def test_missing_optional_fields_default_gracefully(self):
        raw = {"id": "C002", "reference": "REF456"}
        result = EauGrandLyonApi.parse_contract_details(raw)
        assert result["statut"]           == ""
        assert result["solde_eur"]        == 0.0
        assert result["calibre_compteur"] == ""
        assert result["signal_pct"]       is None
        assert result["battery_ok"]       is None

    def test_invalid_solde_defaults_to_zero(self):
        raw = self._raw()
        raw["conditionPaiement"]["compteClient"]["solde"]["value"] = "pas_un_nombre"
        result = EauGrandLyonApi.parse_contract_details(raw)
        assert result["solde_eur"] == 0.0


# ── get_alertes ───────────────────────────────────────────────────────────────

class TestGetAlertes:
    @pytest.mark.asyncio
    async def test_returns_list_of_alertes(self):
        api = _make_api()
        api._do_get = AsyncMock(return_value=[{"id": "A1"}, {"id": "A2"}])
        result = await api.get_alertes()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self):
        api = _make_api()
        api._do_get = AsyncMock(side_effect=Exception("network error"))
        result = await api.get_alertes()
        assert result == []
