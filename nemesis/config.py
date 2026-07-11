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
    # Optionnelle : active les vannes générées par Claude dans !classement.
    anthropic_api_key: str | None = None


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
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
    )
