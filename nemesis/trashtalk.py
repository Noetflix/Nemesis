"""Génération des répliques de trash-talk pour le classement.

Deux sources, dans l'ordre :

1. **IA** (API compatible OpenAI — Groq gratuit par défaut) — si une clé est fournie, un
   seul appel génère une vanne sur mesure par joueur, en voyant tout le classement d'un
   coup. C'est le mode nominal : les phrases sont écrites par le modèle, pas puisées dans
   des tableaux à maintenir.
2. **Repli procédural** — sans clé (ou en cas d'erreur réseau), les phrases sont assemblées
   localement à partir de fragments (étiquette + pique + emoji) selon la position.
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass

from openai import AsyncOpenAI

logger = logging.getLogger("nemesis")

# Consigne donnée au modèle : le ton et le cadre du trash-talk.
_SYSTEME = (
    "Tu es Némésis, un bot Discord qui chambre une bande de potes sur leurs stats "
    "League of Legends. Pour chaque joueur du classement, écris UNE vanne courte "
    "(120 caractères max), drôle et en français, dans un style trash-talk bon enfant "
    "entre amis. Adapte-toi à la position et au rang : chambre le premier pour son "
    "arrogance, achève le dernier, taquine le milieu, raille les non-classés. Reste "
    "piquant sans être méchant ni vulgaire, varie le ton, et termine chaque vanne par "
    "un emoji pertinent. Réponds UNIQUEMENT en JSON."
)

# Catégories de position, de la meilleure à la pire.
TOP = "top"
MID = "mid"
LAST = "last"
UNRANKED = "unranked"


@dataclass(frozen=True)
class _Banque:
    """Fragments assemblables pour une catégorie de position.

    - `etiquettes` : groupe nominal qui qualifie le joueur (« Le boss final »).
    - `piques` : proposition indépendante, la vanne (« personne ne conteste »).
    - `emojis` : ponctuation visuelle finale.
    - `gabarits` : structures de phrase à trous (placeholders nommés).
    """

    etiquettes: tuple[str, ...]
    piques: tuple[str, ...]
    emojis: tuple[str, ...]
    gabarits: tuple[str, ...]


# Gabarits partagés (les plus neutres, valables partout).
_GABARITS_COMMUNS: tuple[str, ...] = (
    "{etiquette}, {pique} {emoji}",
    "{etiquette} : {pique} {emoji}",
)

_BANQUES: dict[str, _Banque] = {
    TOP: _Banque(
        etiquettes=(
            "Le boss final",
            "Le patron du serveur",
            "Le GOAT incontesté",
            "Premier de cordée",
            "La légende vivante",
            "Le sommet de la chaîne alimentaire",
        ),
        piques=(
            "personne ne conteste",
            "les autres jouent à un autre jeu",
            "carry activé en permanence",
            "né pour régner",
            "ça commence à être gênant pour les copains",
        ),
        emojis=("👑", "🐐", "🔥", "🧠", "💪"),
        gabarits=_GABARITS_COMMUNS + ("Tout en haut : {pique} {emoji}",),
    ),
    MID: _Banque(
        etiquettes=(
            "Le ventre mou",
            "Le stratège de l'ombre",
            "Le milieu de tableau",
            "L'éternel outsider",
            "Le sans-histoire",
        ),
        piques=(
            "ni gloire ni honte",
            "confortablement installé",
            "toujours pas dernier, c'est déjà ça",
            "on te surveille du coin de l'œil",
            "le classement t'a oublié là",
        ),
        emojis=("🥷", "🛋️", "👀", "🍺", "😐"),
        gabarits=_GABARITS_COMMUNS + ("{position}ᵉ sur {total}… {pique} {emoji}",),
    ),
    LAST: _Banque(
        etiquettes=(
            "La lanterne rouge",
            "Le boulet de service",
            "Le carry inversé",
            "Le fond du classement",
            "Le dernier de la classe",
        ),
        piques=(
            "quelqu'un lui rappelle les règles ?",
            "premier dans nos cœurs, au moins",
            "désinstalle (on plaisante… ou pas)",
            "un vrai talent pour perdre",
            "il reste de la place en dessous ?",
        ),
        emojis=("🔴", "🤡", "💀", "🎪", "💔"),
        gabarits=_GABARITS_COMMUNS + ("Bon dernier : {pique} {emoji}",),
    ),
    UNRANKED: _Banque(
        etiquettes=(
            "Le fantôme des classées",
            "L'invisible",
            "Le mystère non résolu",
            "Le placement éternel",
        ),
        piques=(
            "pas classé, pas de preuves",
            "trop occupé à esquiver la ranked",
            "un elo tellement secret que Riot le cherche encore",
            "reviens quand t'auras un rang",
        ),
        emojis=("🕵️", "👻", "🫥", "😴"),
        gabarits=_GABARITS_COMMUNS + ("{etiquette} {emoji}",),
    ),
}


@dataclass(frozen=True)
class LigneClassement:
    """Un joueur du classement, tel que présenté au générateur de vannes."""

    position: int
    total: int
    nom: str
    rang: str  # ex. « Gold II (44 LP, 58% WR) » ou « Non classé ».
    is_ranked: bool


async def generer_vannes(
    lignes: list[LigneClassement], *, api_key: str | None, base_url: str, model: str
) -> list[str]:
    """Renvoie une vanne par joueur (dans l'ordre) via l'IA, ou le repli procédural.

    Ne lève jamais : toute erreur (pas de clé, réseau, réponse invalide) retombe sur le
    générateur local pour ne pas casser l'affichage du classement.
    """
    if not api_key:
        return [generer(ligne.position, ligne.total, ligne.is_ranked) for ligne in lignes]
    try:
        return await _generer_via_llm(lignes, api_key, base_url, model)
    except Exception:  # noqa: BLE001 — l'IA est un bonus, jamais un point de rupture.
        logger.warning("Vannes IA indisponibles, repli sur le générateur local.", exc_info=True)
        return [generer(ligne.position, ligne.total, ligne.is_ranked) for ligne in lignes]


async def _generer_via_llm(
    lignes: list[LigneClassement], api_key: str, base_url: str, model: str
) -> list[str]:
    """Un seul appel (API compatible OpenAI) renvoie toutes les vannes en JSON."""
    classement = "\n".join(f"{ligne.position}. {ligne.nom} — {ligne.rang}" for ligne in lignes)
    message = (
        f"Voici le classement Solo/Duo de la team, du meilleur au pire :\n\n{classement}\n\n"
        f"Renvoie exactement {len(lignes)} vannes, une par joueur, dans le même ordre, "
        'sous la forme JSON : {"vannes": ["...", "..."]}.'
    )

    async with AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=1024,
            temperature=1.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEME},
                {"role": "user", "content": message},
            ],
        )

    texte = response.choices[0].message.content or ""
    vannes = json.loads(texte)["vannes"]
    if len(vannes) != len(lignes):
        raise ValueError("Nombre de vannes renvoyé différent du nombre de joueurs.")
    return [str(vanne) for vanne in vannes]


def categorie(position: int, total: int, is_ranked: bool) -> str:
    """Détermine la catégorie de trash-talk selon la place au classement."""
    if not is_ranked:
        return UNRANKED
    if position == 1:
        return TOP
    if position >= total:
        return LAST
    return MID


def generer(position: int, total: int, is_ranked: bool) -> str:
    """Assemble une réplique de trash-talk unique pour la position donnée.

    Tire au hasard un gabarit et ses fragments dans la banque de la catégorie, puis
    remplit les trous (y compris la position et le total pour certaines phrases).
    """
    banque = _BANQUES[categorie(position, total, is_ranked)]
    gabarit = random.choice(banque.gabarits)
    return gabarit.format(
        etiquette=random.choice(banque.etiquettes),
        pique=random.choice(banque.piques),
        emoji=random.choice(banque.emojis),
        position=position,
        total=total,
    )


__all__ = ["categorie", "generer"]
