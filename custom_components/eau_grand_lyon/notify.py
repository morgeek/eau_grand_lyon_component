# Services de notifications intelligentes pour Eau du Grand Lyon
"""Services pour notifications Pushover/Telegram et alertes vocales."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service

from .const import DOMAIN
from .coordinator import EauGrandLyonCoordinator

_LOGGER = logging.getLogger(__name__)

# Schémas de validation pour les services
NOTIFY_SCHEMA = vol.Schema({
    vol.Required("message"): cv.string,
    vol.Optional("title"): cv.string,
    vol.Optional("priority", default=0): vol.In([-2, -1, 0, 1, 2]),
    vol.Optional("sound"): cv.string,
    vol.Optional("url"): cv.string,
    vol.Optional("url_title"): cv.string,
})

ALERT_VOICE_SCHEMA = vol.Schema({
    vol.Required("message"): cv.string,
    vol.Optional("language", default="fr"): cv.string,
    vol.Optional("entity_id"): cv.entity_ids,
    vol.Optional("volume_level"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
})


async def async_setup_services(hass: HomeAssistant) -> None:
    """Configure les services de notifications intelligentes."""

    async def async_notify_pushover(call: ServiceCall) -> None:
        """Envoie une notification Pushover."""
        await _async_send_pushover_notification(hass, call.data)

    async def async_notify_telegram(call: ServiceCall) -> None:
        """Envoie une notification Telegram."""
        await _async_send_telegram_notification(hass, call.data)

    async def async_alert_voice(call: ServiceCall) -> None:
        """Envoie une alerte vocale via Google Home/Alexa."""
        await _async_send_voice_alert(hass, call.data)

    async def async_smart_alert(call: ServiceCall) -> None:
        """Déclenche une alerte intelligente basée sur les données."""
        await _async_send_smart_alert(hass, call.data)

    # Enregistrement des services
    async_register_admin_service(
        hass,
        DOMAIN,
        "notify_pushover",
        async_notify_pushover,
        schema=NOTIFY_SCHEMA,
    )

    async_register_admin_service(
        hass,
        DOMAIN,
        "notify_telegram",
        async_notify_telegram,
        schema=NOTIFY_SCHEMA,
    )

    async_register_admin_service(
        hass,
        DOMAIN,
        "alert_voice",
        async_alert_voice,
        schema=ALERT_VOICE_SCHEMA,
    )

    async_register_admin_service(
        hass,
        DOMAIN,
        "smart_alert",
        async_smart_alert,
        schema=vol.Schema({
            vol.Required("alert_type"): vol.In([
                "high_consumption", "leak_detected", "payment_due",
                "contract_issue", "maintenance_needed"
            ]),
            vol.Optional("contract_ref"): cv.string,
        }),
    )

    _LOGGER.info("Services de notifications intelligentes configurés")


async def _async_send_pushover_notification(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Envoie une notification via Pushover."""
    try:
        service_data = {
            "message": data["message"],
            "title": data.get("title", "Eau du Grand Lyon"),
            "data": {
                "priority": data.get("priority", 0),
            }
        }

        if "sound" in data:
            service_data["data"]["sound"] = data["sound"]
        if "url" in data:
            service_data["data"]["url"] = data["url"]
        if "url_title" in data:
            service_data["data"]["url_title"] = data["url_title"]

        await hass.services.async_call(
            "notify", "pushover", service_data, blocking=True
        )
        _LOGGER.debug("Notification Pushover envoyée: %s", data["message"])

    except Exception as err:
        _LOGGER.error("Erreur envoi notification Pushover: %s", err)


async def _async_send_telegram_notification(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Envoie une notification via Telegram."""
    try:
        service_data = {
            "message": data["message"],
            "title": data.get("title", "🚰 Eau du Grand Lyon"),
            "data": {
                "disable_notification": data.get("priority", 0) < 0,
            }
        }

        if data.get("priority", 0) > 0:
            service_data["message"] = f"🚨 {service_data['message']}"

        await hass.services.async_call(
            "notify", "telegram", service_data, blocking=True
        )
        _LOGGER.debug("Notification Telegram envoyée: %s", data["message"])

    except Exception as err:
        _LOGGER.error("Erreur envoi notification Telegram: %s", err)


async def _async_send_voice_alert(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Envoie une alerte vocale via Google Home/Alexa."""
    try:
        message = data["message"]
        language = data.get("language", "fr")
        entity_ids = data.get("entity_id", [])
        volume_level = data.get("volume_level")

        # Si aucun entity_id spécifié, chercher tous les devices TTS
        if not entity_ids:
            entity_ids = []
            for entity_id in hass.states.async_entity_ids("tts"):
                if "google" in entity_id.lower() or "alexa" in entity_id.lower():
                    entity_ids.append(entity_id)

        if not entity_ids:
            _LOGGER.warning("Aucun device TTS trouvé pour les alertes vocales")
            return

        # Ajuster le volume si demandé
        if volume_level is not None:
            for entity_id in entity_ids:
                await hass.services.async_call(
                    "media_player", "volume_set",
                    {"entity_id": entity_id, "volume_level": volume_level},
                    blocking=True
                )

        # Envoyer le message TTS
        for entity_id in entity_ids:
            await hass.services.async_call(
                "tts", "google_translate_say" if "google" in entity_id else "amazon_polly_say",
                {
                    "entity_id": entity_id,
                    "message": message,
                    "language": language,
                },
                blocking=True
            )

        _LOGGER.debug("Alerte vocale envoyée: %s", message)

    except Exception as err:
        _LOGGER.error("Erreur envoi alerte vocale: %s", err)


async def _async_send_smart_alert(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Envoie une alerte intelligente basée sur les données des sensors."""
    alert_type = data["alert_type"]
    contract_ref = data.get("contract_ref")

    # Récupérer les données des coordinators
    coordinators = hass.data.get(DOMAIN, {})

    if not coordinators:
        _LOGGER.warning("Aucun coordinator trouvé pour les alertes intelligentes")
        return

    # Utiliser le premier coordinator disponible
    coordinator = next(iter(coordinators.values()))
    contract_data = None

    if contract_ref:
        contract_data = coordinator.data.get("contracts", {}).get(contract_ref)
    else:
        # Prendre le premier contrat disponible
        contracts = coordinator.data.get("contracts", {})
        if contracts:
            contract_ref = next(iter(contracts.keys()))
            contract_data = contracts[contract_ref]

    if not contract_data:
        _LOGGER.warning("Aucune donnée de contrat trouvée pour l'alerte intelligente")
        return

    # Générer le message selon le type d'alerte
    message = _generate_smart_alert_message(alert_type, contract_data, contract_ref)

    if message:
        # Envoyer via tous les canaux configurés
        await _async_send_multichannel_alert(hass, message, alert_type)


def _generate_smart_alert_message(alert_type: str, contract_data: dict, contract_ref: str) -> str | None:
    """Génère un message d'alerte intelligente."""
    if alert_type == "high_consumption":
        conso_courant = contract_data.get("consommation_mois_courant", 0)
        conso_precedent = contract_data.get("consommation_mois_precedent", 0)
        if conso_courant and conso_precedent and conso_courant > conso_precedent * 1.5:
            return (f"🚨 Consommation élevée détectée sur le contrat {contract_ref} ! "
                   f"Ce mois: {conso_courant:.1f} m³ vs {conso_precedent:.1f} m³ le mois dernier. "
                   f"Vérifiez s'il n'y a pas de fuite.")

    elif alert_type == "leak_detected":
        # Logique de détection de fuite basée sur les données
        conso_7j = contract_data.get("consommation_7j", 0)
        conso_30j = contract_data.get("consommation_30j", 0)
        if conso_7j and conso_30j and conso_7j > (conso_30j / 4) * 2:
            return (f"🚨 Possible fuite détectée sur le contrat {contract_ref} ! "
                   f"Consommation 7 jours: {conso_7j:.1f} m³, moyenne 30 jours: {conso_30j/4:.1f} m³/jour. "
                   f"Vérifiez vos installations.")

    elif alert_type == "payment_due":
        solde = contract_data.get("solde_eur", 0)
        date_echeance = contract_data.get("date_echeance")
        if solde < -50 and date_echeance:
            return (f"💰 Paiement en retard pour le contrat {contract_ref}. "
                   f"Solde: {solde:.2f} €, échéance: {date_echeance}. "
                   f"N'oubliez pas de régulariser.")

    elif alert_type == "contract_issue":
        statut = contract_data.get("statut", "")
        if statut and "suspendu" in statut.lower():
            return (f"⚠️ Problème de contrat détecté pour {contract_ref}. "
                   f"Statut: {statut}. Contactez le service client.")

    elif alert_type == "maintenance_needed":
        # Alerte basée sur la consommation annuelle ou l'âge du compteur
        conso_annuelle = contract_data.get("consommation_annuelle", 0)
        if conso_annuelle > 2000:  # Seuil arbitraire pour alerte maintenance
            return (f"🔧 Maintenance recommandée pour le contrat {contract_ref}. "
                   f"Consommation annuelle élevée: {conso_annuelle:.1f} m³. "
                   f"Vérifiez l'état de vos installations.")

    return None


async def _async_send_multichannel_alert(hass: HomeAssistant, message: str, alert_type: str) -> None:
    """Envoie une alerte sur tous les canaux configurés."""
    priority = 1 if alert_type in ["leak_detected", "high_consumption"] else 0

    # Pushover
    try:
        await _async_send_pushover_notification(hass, {
            "message": message,
            "priority": priority,
            "sound": "siren" if priority > 0 else "pushover"
        })
    except Exception:
        pass  # Ignore si Pushover n'est pas configuré

    # Telegram
    try:
        await _async_send_telegram_notification(hass, {
            "message": message,
            "priority": priority
        })
    except Exception:
        pass  # Ignore si Telegram n'est pas configuré

    # Alerte vocale pour les alertes critiques
    if priority > 0:
        try:
            await _async_send_voice_alert(hass, {
                "message": f"Alerte eau du Grand Lyon: {message}",
                "language": "fr"
            })
        except Exception:
            pass  # Ignore si TTS n'est pas configuré