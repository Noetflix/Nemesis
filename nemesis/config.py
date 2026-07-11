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
    )


def _int_ou_none(valeur: str | None) -> int | None:
    """Convertit une variable d'environnement en entier, ou None si vide/invalide."""
    if not valeur or not valeur.strip().isdigit():
        return None
    return int(valeur.strip())
