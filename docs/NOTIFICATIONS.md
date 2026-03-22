# Guide des Notifications Intelligentes
# Eau du Grand Lyon pour Home Assistant

## Vue d'ensemble

L'intégration Eau du Grand Lyon inclut un système complet de notifications intelligentes qui peut vous alerter automatiquement sur les événements importants liés à votre consommation d'eau.

## Services disponibles

### 1. `eau_grand_lyon.notify_pushover`
Envoie une notification via Pushover.

**Paramètres :**
- `message` (requis) : Le message à envoyer
- `title` (optionnel) : Titre de la notification (défaut: "Eau du Grand Lyon")
- `priority` (optionnel) : Priorité (-2 à 2, défaut: 0)
- `sound` (optionnel) : Son Pushover à utiliser
- `url` / `url_title` (optionnel) : Lien à inclure

**Exemple :**
```yaml
service: eau_grand_lyon.notify_pushover
data:
  message: "Consommation élevée détectée !"
  title: "Alerte Eau"
  priority: 1
  sound: siren
```

### 2. `eau_grand_lyon.notify_telegram`
Envoie une notification via Telegram.

**Paramètres :**
- `message` (requis) : Le message à envoyer
- `title` (optionnel) : Titre (défaut: "🚰 Eau du Grand Lyon")
- `priority` (optionnel) : Priorité (affecte le format)

**Exemple :**
```yaml
service: eau_grand_lyon.notify_telegram
data:
  message: "Résumé quotidien disponible"
  priority: -1  # Notification silencieuse
```

### 3. `eau_grand_lyon.alert_voice`
Envoie une alerte vocale via Google Home/Alexa.

**Paramètres :**
- `message` (requis) : Message à annoncer
- `language` (optionnel) : Langue (défaut: "fr")
- `entity_id` (optionnel) : Liste des devices TTS
- `volume_level` (optionnel) : Volume (0.0 à 1.0)

**Exemple :**
```yaml
service: eau_grand_lyon.alert_voice
data:
  message: "Alerte importante : possible fuite détectée"
  volume_level: 0.8
```

### 4. `eau_grand_lyon.smart_alert`
Déclenche une alerte intelligente basée sur l'analyse des données.

**Paramètres :**
- `alert_type` (requis) : Type d'alerte
- `contract_ref` (optionnel) : Référence du contrat

**Types d'alertes :**
- `high_consumption` : Consommation élevée vs mois précédent
- `leak_detected` : Possible fuite (analyse journalière)
- `payment_due` : Paiement en retard
- `contract_issue` : Problème de statut contrat
- `maintenance_needed` : Maintenance recommandée

**Exemple :**
```yaml
service: eau_grand_lyon.smart_alert
data:
  alert_type: leak_detected
```

## Configuration requise

### Pushover
Ajoutez dans `configuration.yaml` :
```yaml
notify:
  - name: pushover
    platform: pushover
    api_key: "YOUR_API_KEY"
    user_key: "YOUR_USER_KEY"
```

### Telegram
```yaml
notify:
  - name: telegram
    platform: telegram_bot
    api_key: "YOUR_BOT_TOKEN"
    chat_id: "YOUR_CHAT_ID"
```

### TTS (Google Home/Alexa)
```yaml
tts:
  - platform: google_translate
    language: fr
    tld: fr
```

## Automatisations incluses

### Alerte consommation élevée
- Détecte automatiquement une consommation > 150% du mois précédent
- Envoie des notifications sur tous les canaux configurés

### Alerte possible fuite
- Analyse la consommation des 7 derniers jours vs 30 jours
- Alerte si consommation journalière anormalement élevée

### Rappel paiement
- Vérifie quotidiennement les soldes négatifs
- Rappelle les échéances proches

### Résumé quotidien
- Envoie un résumé à 20h00 (notification silencieuse)
- Inclut consommation, coûts, solde

### Alerte maintenance
- Tous les premiers du mois si consommation annuelle > 2000 m³
- Suggère une vérification des installations

## Personnalisation

### Modifier les seuils d'alerte
Éditez les automatisations pour ajuster :
- Seuil de consommation élevée (actuellement 1.5x)
- Seuil de détection fuite (actuellement 2x la moyenne)
- Seuil de solde négatif (actuellement -10€)
- Seuil de maintenance (actuellement 2000 m³/an)

### Ajouter de nouveaux canaux
Modifiez `_async_send_multichannel_alert()` dans `notify.py` pour ajouter :
- Email
- SMS
- Autres services de notification

### Alertes vocales ciblées
Spécifiez `entity_id` pour limiter aux devices souhaités :
```yaml
entity_id: media_player.google_home_salon
```

## Dépannage

### Notifications non reçues
1. Vérifiez la configuration des services de notification
2. Testez manuellement les services depuis Outils de développement > Services
3. Vérifiez les logs HA pour les erreurs

### Alertes vocales ne fonctionnent pas
1. Assurez-vous que TTS est configuré
2. Vérifiez que les devices sont disponibles
3. Testez TTS directement depuis HA

### Trop d'alertes
1. Ajustez les seuils dans les automatisations
2. Ajoutez des conditions supplémentaires
3. Utilisez des modes `single` ou `queued` pour éviter le spam

## Sécurité

- Les notifications incluent des informations sensibles (consommation, coûts)
- Configurez les autorisations appropriées pour les utilisateurs
- Utilisez des tokens sécurisés pour les API externes
- Évitez les alertes sensibles sur des canaux non sécurisés