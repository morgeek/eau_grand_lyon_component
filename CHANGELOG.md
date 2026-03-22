# Changelog

Tous les changements notables apportés à cette intégration seront documentés dans ce fichier.

Le format est basé sur [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
et cette intégration adhère au [Versionnage Sémantique](https://semver.org/spec/v2.0.0.html).

## [2.2.4] - 2026-03-22

### Ajouté
- **Mode hors-ligne** : si l'API est indisponible après les retries, les sensors restent disponibles avec les dernières données connues (cache local persistant)
- Le sensor "Statut API" affiche `HORS-LIGNE` en mode cache, avec les attributs `offline_since` et `note`
- Le cache est sauvegardé sur disque — survit à un redémarrage de Home Assistant

### Corrigé
- Bug : variable `now` utilisée avant d'être définie dans `_async_update_data`

## [2.2.3] - 2026-03-22

### Corrigé
- Imports manquants dans `config_flow.py` (`logging`, `aiohttp`, `Any`) — crash au chargement
- Remplacement de `.json(content_type=None)` déprécié par `json.loads()` — compatibilité aiohttp 4.x
- Sécurisation des conversions de type dans `format_consumptions`, `format_daily_consumptions`, `parse_contract_details`
- Rate limiting basé sur `time.monotonic()` au lieu de `datetime.now()` — insensible aux changements d'heure
- Validation du type de réponse API dans `get_contracts` et `get_monthly_consumptions`
- Protection des accès directs aux champs dans `_inject_statistics`
- Version alignée dans `manifest.json`

### Modifié
- Déduplication du `device_info` des sensors globaux via classe de base `_EauGrandLyonGlobalBase`
- Déduplication du calcul `last_reset` via propriété `_current_year_str`

## [2.2.1] - 2024-12-15

### Ajouté
- Validation plus stricte des configurations au démarrage (format email, longueur mot de passe)
- Gestion d'erreurs plus spécifique dans l'API et le coordinateur
- Amélioration des logs pour le débogage

### Modifié
- Remplacement des `except Exception` génériques par des exceptions plus spécifiques
- Amélioration de la validation des données d'entrée

### Corrigé
- Gestion plus robuste des erreurs de parsing JSON et réseau

## [2.2.0] - 2024-11-XX

### Ajouté
- Support des consommations journalières (si disponible)
- Détection des mois manquants dans l'historique
- Intégration Energy Dashboard avec sensors optimisés
- Templates Lovelace complets

### Modifié
- Amélioration de la gestion des erreurs réseau avec retry
- Optimisation des appels API

## [2.1.0] - 2024-10-XX

### Ajouté
- Notifications d'alertes persistantes
- Bouton de mise à jour manuelle
- Support des coûts configurables

### Modifié
- Refactorisation de l'architecture (coordinateur + API séparés)

## [2.0.0] - 2024-09-XX

### Ajouté
- Authentification PKCE complète
- Support multi-contrats
- Sensors pour solde, statut contrat, échéance

### Modifié
- Changement majeur de l'API d'authentification

## [1.0.0] - 2024-08-XX

### Ajouté
- Intégration initiale avec sensors de consommation
- Authentification basique
- Support d'un seul contrat