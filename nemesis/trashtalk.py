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
    "Tu es Némésis, un bot Discord qui chambre une bande de potes sur leurs statistiques "
    "League of Legends. Pour chaque joueur du classement, écris UNE vanne plus ou moins courte "
    "(120 caractères maximum), drôle, en français, dans un style de trash-talk bon enfant "
    "entre amis mais qui peut être un peu hard (sans être excessif). Adapte systématiquement chaque vanne à la situation du joueur dans le classement : "
    "sa position, son rang, son avance ou son retard sur les autres, les écarts de LP, les égalités, "
    "les batailles serrées, les gros écarts, les remontées, les chutes, les non-classés et toute "
    "situation notable. Le contexte du classement doit être au cœur de la vanne. "
    "Le premier peut être glorifié de façon exagérée, les poursuivants mis sous pression, "
    "le milieu de tableau taquiné, les joueurs décrochés tournés en dérision et le dernier "
    "gentiment achevé. Si deux joueurs sont très proches, souligne leur duel. Si un joueur est "
    "loin devant ou très loin derrière, insiste sur cet écart. Varie le ton, évite les répétitions, "
    "tu peux être aggressif et sans filtre, et termine chaque vanne par un emoji pertinent. "
    "Réponds UNIQUEMENT en JSON."
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


# --- Commentaire d'une partie terminée (notification de fin de game) ---------------------

# Consigne au modèle pour commenter UNE partie qui vient de finir.
_SYSTEME_PARTIE = (
    "Tu es Némésis, un bot Discord qui chambre une bande de potes sur League of Legends. "
    "Une partie classée vient de se terminer pour l'un d'eux. Écris UNE seule phrase (140 "
    "caractères max), en français, dans un style trash-talk bon enfant entre amis mais qui "
    "peut piquer. Sur une victoire, glorifie ou charrie selon la performance ; sur une "
    "défaite, chambre sans pitié (ou console ironiquement si le joueur a bien joué malgré "
    "la défaite). Appuie-toi sur les stats fournies (KDA, rôle, champion, dégâts, multikills, "
    "farm) pour viser juste : un gros KDA se célèbre, un feed se moque, un pentakill se "
    "commente. Termine par un emoji pertinent. Réponds UNIQUEMENT avec la phrase, sans "
    "guillemets ni préfixe."
)

# Répliques de secours locales selon victoire/défaite et qualité du KDA.
_PARTIE_VICTOIRE_CARRY: tuple[str, ...] = (
    "Victoire méritée, ce soir c'est toi le patron 👑",
    "GG, t'as porté la game sur ton dos 💪",
    "Un carry pareil, c'en est presque gênant pour les autres 🔥",
)
_PARTIE_VICTOIRE_FLUKE: tuple[str, ...] = (
    "Victoire… grâce à la team surtout, avoue 😏",
    "T'as gagné mais on va gentiment oublier ton score 🙈",
    "W dans les stats, mais la vraie MVP c'était pas toi 🍀",
)
_PARTIE_DEFAITE_HONNEUR: tuple[str, ...] = (
    "Défaite, mais toi t'as tenu la baraque, la team a coulé 🫡",
    "Perdu malgré un beau match : la loterie du solo Q 🎰",
    "Bien joué dans la défaite, c'est les autres qu'il faut gronder 😤",
)
_PARTIE_DEFAITE_BOULET: tuple[str, ...] = (
    "Défaite… et à voir ton KDA, on sait un peu à qui la faute 💀",
    "Perdu, feed inclus. On désinstalle ? (on plaisante… ou pas) 🤡",
    "Cette game, on va faire comme si elle n'avait jamais existé 🙃",
)


@dataclass(frozen=True)
class PerfPartie:
    """Résumé d'une partie, tel que présenté au générateur de commentaire."""

    nom: str
    champion: str
    role: str
    queue: str
    win: bool
    kills: int
    deaths: int
    assists: int
    kda: float
    cs_per_min: float
    degats: int
    vision: int
    multikill: str | None


async def generer_vanne_partie(
    perf: PerfPartie, *, api_key: str | None, base_url: str, model: str
) -> str:
    """Renvoie un commentaire de trash-talk pour une partie via l'IA, ou le repli local.

    Ne lève jamais : toute erreur retombe sur le générateur procédural.
    """
    if not api_key:
        return generer_partie(perf.win, perf.kda)
    try:
        return await _generer_partie_via_llm(perf, api_key, base_url, model)
    except Exception:  # noqa: BLE001 — l'IA est un bonus, jamais un point de rupture.
        logger.warning("Commentaire IA indisponible, repli sur le générateur local.", exc_info=True)
        return generer_partie(perf.win, perf.kda)


async def _generer_partie_via_llm(perf: PerfPartie, api_key: str, base_url: str, model: str) -> str:
    """Un appel (API compatible OpenAI) renvoie le commentaire de la partie."""
    issue = "VICTOIRE" if perf.win else "DÉFAITE"
    role = f" ({perf.role})" if perf.role else ""
    multi = f", {perf.multikill}" if perf.multikill else ""
    message = (
        f"{perf.nom} vient de finir une {perf.queue} en {issue}.\n"
        f"Champion : {perf.champion}{role}. "
        f"KDA : {perf.kills}/{perf.deaths}/{perf.assists} (ratio {perf.kda:.1f}){multi}. "
        f"Farm : {perf.cs_per_min:.1f} cs/min. "
        f"Dégâts aux champions : {perf.degats}. Score de vision : {perf.vision}.\n"
        "Écris le commentaire."
    )

    async with AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
        response = await client.chat.completions.create(
            model=model,
            max_tokens=200,
            temperature=1.0,
            messages=[
                {"role": "system", "content": _SYSTEME_PARTIE},
                {"role": "user", "content": message},
            ],
        )
    texte = (response.choices[0].message.content or "").strip()
    if not texte:
        raise ValueError("Commentaire vide renvoyé par le modèle.")
    return texte


def generer_partie(win: bool, kda: float) -> str:
    """Commentaire de secours local selon l'issue et la qualité du KDA (seuil 2.5)."""
    bien_joue = kda >= 2.5
    if win:
        pool = _PARTIE_VICTOIRE_CARRY if bien_joue else _PARTIE_VICTOIRE_FLUKE
    else:
        pool = _PARTIE_DEFAITE_HONNEUR if bien_joue else _PARTIE_DEFAITE_BOULET
    return random.choice(pool)


# --- Commentaire d'un duel (commande !versus) --------------------------------------------

_SYSTEME_DUEL = (
    "Tu es Némésis, un bot Discord qui chambre une bande de potes sur League of Legends. "
    "On te donne un face-à-face entre deux joueurs. Écris UNE phrase (140 caractères max), "
    "en français, style trash-talk bon enfant mais qui pique : glorifie ou charrie celui qui "
    "mène, chambre celui qui est derrière, et souligne l'écart (serré ou humiliant). Termine "
    "par un emoji. Réponds UNIQUEMENT avec la phrase, sans guillemets ni préfixe."
)

_DUEL_ECRASANT: tuple[str, ...] = (
    "{gagnant} roule sur {perdant}, ce n'est même plus un duel c'est une leçon 📚",
    "{perdant} ramasse les miettes pendant que {gagnant} banquette au sommet 🍗",
    "{gagnant} vs {perdant} : appelez les secours pour {perdant} 🚑",
)
_DUEL_SERRE: tuple[str, ...] = (
    "{gagnant} devance {perdant} d'un cheveu, la revanche va faire mal 🔥",
    "Duel au couteau : {gagnant} passe devant {perdant}, mais ça se joue à rien ⚔️",
    "{gagnant} et {perdant} se tiennent, un mauvais LP et tout bascule 😬",
)


async def generer_vanne_duel(
    gagnant: str,
    rang_gagnant: str,
    perdant: str,
    rang_perdant: str,
    *,
    ecart_serre: bool,
    api_key: str | None,
    base_url: str,
    model: str,
) -> str:
    """Renvoie un commentaire de duel via l'IA, ou le repli local. Ne lève jamais."""
    if not api_key:
        return generer_duel(gagnant, perdant, ecart_serre)
    try:
        message = (
            f"Face-à-face :\n- {gagnant} : {rang_gagnant} (devant)\n"
            f"- {perdant} : {rang_perdant} (derrière)\n"
            f"L'écart est {'serré' if ecart_serre else 'important'}. Écris le commentaire."
        )
        async with AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=200,
                temperature=1.0,
                messages=[
                    {"role": "system", "content": _SYSTEME_DUEL},
                    {"role": "user", "content": message},
                ],
            )
        texte = (response.choices[0].message.content or "").strip()
        if not texte:
            raise ValueError("Commentaire de duel vide.")
        return texte
    except Exception:  # noqa: BLE001 — l'IA est un bonus, jamais un point de rupture.
        logger.warning("Vanne de duel IA indisponible, repli sur le générateur local.")
        return generer_duel(gagnant, perdant, ecart_serre)


def generer_duel(gagnant: str, perdant: str, ecart_serre: bool) -> str:
    """Commentaire de duel de secours local."""
    pool = _DUEL_SERRE if ecart_serre else _DUEL_ECRASANT
    return random.choice(pool).format(gagnant=gagnant, perdant=perdant)


# --- Alerte « en game » (commande temps réel) --------------------------------------------

_EN_GAME: tuple[str, ...] = (
    "{nom} lance une game sur {champion}, priez pour ses coéquipiers 🙏",
    "🚨 {nom} est en ranked sur {champion}, LP en jeu, sueurs froides garanties 😰",
    "{nom} sort le {champion}, le serveur retient son souffle 🎮",
    "Alerte : {nom} tente sa chance sur {champion}. Montée ou tragédie ? 🎲",
    "{nom} enfourche {champion} pour la gloire (ou la honte) 🏇",
)


def generer_vanne_en_game(nom: str, champion: str) -> str:
    """Petite accroche locale pour l'alerte « en game »."""
    return random.choice(_EN_GAME).format(nom=nom, champion=champion)


__all__ = [
    "PerfPartie",
    "categorie",
    "generer",
    "generer_duel",
    "generer_partie",
    "generer_vanne_duel",
    "generer_vanne_en_game",
    "generer_vanne_partie",
]
