"""Chargement de la configuration et des secrets depuis l'environnement (.env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Configuration immuable du bot, chargée au démarrage."""

    discord_token: str
    riot_api_key: str
    command_prefix: str = "!"
    default_platform: str = "euw1"
    # LLM (compatible OpenAI) pour les vannes du !classement. La clé est optionnelle :
    # sans elle, un générateur local prend le relais. Défauts = Groq (gratuit).
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "llama-3.3-70b-versatile"
    # Classement automatique. Sans salon défini, la planification est désactivée.
    classement_channel_id: int | None = None
    classement_heures: str = "10:00,20:00"  # heures « HH:MM » séparées par des virgules
    classement_tz: str = "Europe/Paris"
    # Notification de fin de partie (classé solo/duo + flex). Salon dédié ; à défaut,
    # on retombe sur le salon du classement. Sans aucun salon, la surveillance est off.
    match_notif_channel_id: int | None = None
    match_poll_minutes: int = 5  # intervalle de vérification des nouvelles parties
    # GIF de victoire/défaite via Giphy (optionnel). Sans clé, un GIF de la liste curée
    # intégrée est utilisé : la notif a donc toujours un GIF.
    giphy_api_key: str | None = None
    giphy_requete_victoire: str = "league of legends victory celebration"
    giphy_requete_defaite: str = "sad defeat fail"
    # Tableau de bord des stats. Le bot enregistre son activité dans un SQLite et
    # l'expose via un petit serveur JSON, consommé par l'app bureau (voir desktop/).
    # stats_api_host = 127.0.0.1 en local ; passer à 0.0.0.0 sur un VPS pour l'exposer.
    stats_enabled: bool = True
    stats_db_path: str = "data/stats.db"
    stats_api_host: str = "127.0.0.1"
    stats_api_port: int = 8787
    stats_bot_name: str = "nemesis"  # identifiant du bot (préparé pour le multi-bots)

    @property
    def match_channel_effectif(self) -> int | None:
        """Salon de notification de partie, avec repli sur le salon du classement."""
        return self.match_notif_channel_id or self.classement_channel_id


def load_config() -> Config:
    """Charge le .env puis construit la Config.

    Lève une ValueError claire si un secret obligatoire manque.
    """
    load_dotenv()

    discord_token = os.getenv("DISCORD_TOKEN")
    riot_api_key = os.getenv("RIOT_API_KEY")

    # Variables obligatoires : on liste précisément ce qui manque.
    manquantes = [
        nom
        for nom, valeur in (
            ("DISCORD_TOKEN", discord_token),
            ("RIOT_API_KEY", riot_api_key),
        )
        if not valeur
    ]
    if manquantes:
        raise ValueError(
            "Variables d'environnement manquantes : "
            + ", ".join(manquantes)
            + ". Copiez .env.example vers .env et renseignez ces valeurs."
        )

    # À ce stade, mypy/l'analyse statique savent que ces valeurs sont non nulles.
    assert discord_token is not None
    assert riot_api_key is not None

    return Config(
        discord_token=discord_token,
        riot_api_key=riot_api_key,
        command_prefix=os.getenv("COMMAND_PREFIX", "!"),
        default_platform=os.getenv("DEFAULT_PLATFORM", "euw1"),
        llm_api_key=os.getenv("LLM_API_KEY"),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        llm_model=os.getenv("LLM_MODEL", "llama-3.3-70b-versatile"),
        classement_channel_id=_int_ou_none(os.getenv("CLASSEMENT_CHANNEL_ID")),
        classement_heures=os.getenv("CLASSEMENT_HEURES", "10:00,20:00"),
        classement_tz=os.getenv("CLASSEMENT_TZ", "Europe/Paris"),
        match_notif_channel_id=_int_ou_none(os.getenv("MATCH_NOTIF_CHANNEL_ID")),
        match_poll_minutes=_int_positif(os.getenv("MATCH_POLL_MINUTES"), defaut=5),
        giphy_api_key=os.getenv("GIPHY_API_KEY"),
        giphy_requete_victoire=os.getenv(
            "GIPHY_REQUETE_VICTOIRE", "league of legends victory celebration"
        ),
        giphy_requete_defaite=os.getenv("GIPHY_REQUETE_DEFAITE", "sad defeat fail"),
        stats_enabled=_bool_env(os.getenv("STATS_ENABLED"), defaut=True),
        stats_db_path=os.getenv("STATS_DB_PATH", "data/stats.db"),
        stats_api_host=os.getenv("STATS_API_HOST", "127.0.0.1"),
        stats_api_port=_int_positif(os.getenv("STATS_API_PORT"), defaut=8787),
        stats_bot_name=os.getenv("STATS_BOT_NAME", "nemesis"),
    )


def _int_ou_none(valeur: str | None) -> int | None:
    """Convertit une variable d'environnement en entier, ou None si vide/invalide."""
    if not valeur or not valeur.strip().isdigit():
        return None
    return int(valeur.strip())


def _int_positif(valeur: str | None, *, defaut: int) -> int:
    """Entier strictement positif depuis l'environnement, sinon la valeur par défaut."""
    entier = _int_ou_none(valeur)
    return entier if entier and entier > 0 else defaut


def _bool_env(valeur: str | None, *, defaut: bool) -> bool:
    """Interprète une variable d'environnement comme booléen (1/true/oui/on)."""
    if valeur is None:
        return defaut
    return valeur.strip().lower() in {"1", "true", "vrai", "oui", "yes", "on"}
