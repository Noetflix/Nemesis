"""Générateur de répliques de trash-talk pour le classement.

Les phrases ne sont pas écrites en dur : elles sont **assemblées** à la volée à partir de
fragments (étiquette + pique + emoji) selon la position du joueur au classement. Chaque
catégorie combine ses banques de mots, ce qui donne des dizaines de variantes possibles.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

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
