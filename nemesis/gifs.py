"""Récupération d'un GIF de victoire / défaite pour la notification de fin de partie.

Deux sources, dans l'ordre :

1. **Giphy** — si une clé API est fournie, une recherche renvoie un GIF varié sur mesure
   (clé beta gratuite et instantanée sur developers.giphy.com).
2. **Liste curée** — sans clé (ou en cas d'erreur réseau), un GIF est tiré d'un petit pool
   d'URLs codées en dur et vérifiées. Toujours disponible : la notif a donc toujours un GIF.
"""

from __future__ import annotations

import logging
import random

import aiohttp

logger = logging.getLogger("nemesis")

_GIPHY_ENDPOINT = "https://api.giphy.com/v1/gifs/search"

# Nombre de résultats Giphy parmi lesquels tirer au hasard, pour varier les GIF.
_LIMIT = 25

# Repli local : pools d'URLs de GIF vérifiées (200), tirage aléatoire selon l'issue.
_GIF_VICTOIRE: tuple[str, ...] = (
    "https://media.giphy.com/media/eIU6v9ipMUdxH9Ddw3/giphy.gif",
    "https://media.giphy.com/media/1AHCDNL12A3x5Mixzd/giphy.gif",
    "https://media.giphy.com/media/BWC3nlr8h1hxGwhclr/giphy.gif",
    "https://media.giphy.com/media/xT8qBqSjMYEDWsqptC/giphy.gif",
    "https://media.giphy.com/media/2PrVqyxXoGWt2/giphy.gif",
)
_GIF_DEFAITE: tuple[str, ...] = (
    "https://media.giphy.com/media/65vWKzmeScoM4Sf7S9/giphy.gif",
    "https://media.giphy.com/media/3oKIPddfYuXVZeItos/giphy.gif",
    "https://media.giphy.com/media/UAnnb1jRHptIrPBUfC/giphy.gif",
    "https://media.giphy.com/media/TTgT05u2A6hVA289Bp/giphy.gif",
    "https://media.giphy.com/media/sR4iEzDv5KmcrDOgQH/giphy.gif",
    "https://media.giphy.com/media/xUPGcCQs8BSBvOQfok/giphy.gif",
)


async def chercher_gif(api_key: str | None, requete: str, win: bool) -> str:
    """Renvoie l'URL d'un GIF illustrant l'issue (victoire/défaite).

    Tente Giphy si une clé est fournie ; à défaut ou en cas d'échec, retombe sur la liste
    curée. Ne lève jamais et renvoie toujours une URL exploitable.
    """
    if api_key:
        url = await _chercher_via_giphy(api_key, requete)
        if url:
            return url
    return random.choice(_GIF_VICTOIRE if win else _GIF_DEFAITE)


async def _chercher_via_giphy(api_key: str, requete: str) -> str | None:
    """Recherche un GIF via l'API Giphy, ou None en cas d'erreur / résultat vide."""
    params = {
        "api_key": api_key,
        "q": requete,
        "limit": str(_LIMIT),
        "rating": "pg-13",
        "lang": "fr",
        "bundle": "messaging_non_clips",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_GIPHY_ENDPOINT, params=params, timeout=10) as reponse:
                reponse.raise_for_status()
                data = await reponse.json()
    except Exception:  # noqa: BLE001 — le GIF est décoratif, on retombe sur la liste curée.
        logger.warning("GIF Giphy indisponible pour %r, repli sur la liste curée.", requete)
        return None
    return _extraire_url(data)


# Renditions Giphy préférées, de la plus large/qualitative à la plus petite. Une rendition
# assez large évite que Discord n'affiche un embed étroit.
_RENDITIONS = ("downsized_large", "original", "downsized_medium", "downsized", "fixed_width")


def _extraire_url(data: dict) -> str | None:
    """Choisit un GIF au hasard parmi les résultats, dans sa meilleure rendition disponible."""
    resultats = list(data.get("data") or [])
    random.shuffle(resultats)
    for resultat in resultats:
        images = resultat.get("images", {})
        for cle in _RENDITIONS:
            url = images.get(cle, {}).get("url")
            if url:
                return url
    return None


__all__ = ["chercher_gif"]
