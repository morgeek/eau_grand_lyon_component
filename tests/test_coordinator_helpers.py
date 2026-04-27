"""Tests for pure coordinator helper functions."""
import pytest

from custom_components.eau_grand_lyon.coordinator import (
    _find_missing_months,
    _parse_nb_habitants,
    _parse_outage_alertes,
)


class TestParseNbHabitants:
    def test_empty_string_returns_1(self):
        assert _parse_nb_habitants("") == 1

    def test_none_like_falsy_returns_1(self):
        assert _parse_nb_habitants(None) == 1  # type: ignore[arg-type]

    def test_extracts_digit_from_phrase(self):
        assert _parse_nb_habitants("4 personnes") == 4

    def test_single_digit_string(self):
        assert _parse_nb_habitants("3") == 3

    def test_no_digit_returns_1(self):
        assert _parse_nb_habitants("plusieurs personnes") == 1

    def test_leading_digit_wins(self):
        assert _parse_nb_habitants("2 adultes et 1 enfant") == 2


class TestFindMissingMonths:
    def test_empty_list_returns_empty(self):
        assert _find_missing_months([]) == []

    def test_single_entry_returns_empty(self):
        assert _find_missing_months([{"annee": 2024, "mois_index": 0, "label": "Jan"}]) == []

    def test_contiguous_months_returns_empty(self, sample_consos):
        assert _find_missing_months(sample_consos) == []

    def test_gap_in_middle_detected(self):
        consos = [
            {"annee": 2024, "mois_index": 0, "label": "Jan", "consommation_m3": 10},
            {"annee": 2024, "mois_index": 2, "label": "Mar", "consommation_m3": 12},
        ]
        missing = _find_missing_months(consos)
        assert len(missing) == 1
        assert "2024" in missing[0]

    def test_year_boundary_gap(self):
        consos = [
            {"annee": 2023, "mois_index": 11, "label": "Dec", "consommation_m3": 10},
            {"annee": 2024, "mois_index":  1, "label": "Feb", "consommation_m3": 12},
        ]
        missing = _find_missing_months(consos)
        assert len(missing) == 1


class TestParseOutageAlertes:
    def test_empty_list_returns_empty(self):
        assert _parse_outage_alertes([]) == []

    def test_travaux_alert_included(self):
        alerte = {
            "id": "42",
            "infosAlarme": {
                "type": {"libelle": "Travaux"},
                "libelle": "Coupure rue X",
                "dateDebut": "2024-06-01T08:00:00",
                "dateFin": "2024-06-01T18:00:00",
                "description": "Travaux réseau",
            },
            "modeleAction": {"libelle": ""},
        }
        result = _parse_outage_alertes([alerte])
        assert len(result) == 1
        assert result[0]["date_debut"] == "2024-06-01"
        assert result[0]["date_fin"] == "2024-06-01"
        assert result[0]["reference"] == "42"

    def test_non_outage_type_excluded(self):
        alerte = {
            "id": "1",
            "infosAlarme": {
                "type": {"libelle": "Facture"},
                "libelle": "Nouvelle facture disponible",
                "dateDebut": "2024-06-01",
            },
            "modeleAction": {"libelle": ""},
        }
        assert _parse_outage_alertes([alerte]) == []

    def test_sorted_by_date_ascending(self):
        def _make(id_, date, keyword):
            return {
                "id": id_,
                "infosAlarme": {
                    "type": {"libelle": keyword},
                    "dateDebut": date,
                },
                "modeleAction": {"libelle": ""},
            }

        alerts = [
            _make("b", "2024-07-15", "COUPURE"),
            _make("a", "2024-06-01", "TRAVAUX"),
        ]
        result = _parse_outage_alertes(alerts)
        assert result[0]["reference"] == "a"
        assert result[1]["reference"] == "b"

    def test_malformed_entry_skipped(self):
        alerts = [{"bad": "data"}, {
            "id": "ok",
            "infosAlarme": {"type": {"libelle": "COUPURE"}, "dateDebut": "2024-01-01"},
            "modeleAction": {"libelle": ""},
        }]
        result = _parse_outage_alertes(alerts)
        assert len(result) == 1
