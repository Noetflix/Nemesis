"""Client de l'API Riot pour League of Legends.

Flux MODERNE (ne jamais utiliser les endpoints par nom d'invocateur, obsolètes) :

    Riot ID (Pseudo#TAG) --Account-V1--> PUUID
    PUUID                --Summoner-V4--> niveau
    PUUID                --League-V4---> rang / LP
    PUUID                --Match-V5----> IDs de parties -> détails

DOUBLE ROUTING (à ne jamais confondre) :
    * PLATEFORME (euw1, na1, kr...) : Summoner-V4 et League-V4 ;
    * CLUSTER régional (europe, americas, asia, sea) : Account-V1 et Match-V5.
"""

from __future__ import annotations

from dataclasses import dataclass

from riotwatcher import ApiError, LolWatcher, RiotWatcher

# Association plateforme -> cluster régional pour Account-V1 et Match-V5.
PLATFORM_TO_REGION: dict[str, str] = {
    "euw1": "europe",
    "eun1": "europe",
    "tr1": "europe",
    "ru": "europe",
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "kr": "asia",
    "jp1": "asia",
    "oc1": "sea",
}


class RiotIdError(ValueError):
    """Riot ID mal formé (le « # » séparateur est absent)."""


@dataclass(frozen=True)
class PlayerSummary:
    """Résumé agrégé des statistiques d'un joueur."""

    game_name: str
    tag_line: str
    level: int
    rank: str
    winrate: str
    recent: list[str]


def parse_riot_id(riot_id: str) -> tuple[str, str]:
    """Découpe « Pseudo#TAG » en (game_name, tag_line).

    Lève RiotIdError si le « # » est manquant.
    """
    if "#" not in riot_id:
        raise RiotIdError("Riot ID invalide : format attendu « Pseudo#TAG ».")
    game_name, _, tag_line = riot_id.partition("#")
    game_name, tag_line = game_name.strip(), tag_line.strip()
    if not game_name or not tag_line:
        raise RiotIdError("Riot ID invalide : le pseudo et le tag sont obligatoires.")
    return game_name, tag_line


class RiotClient:
    """Client de haut niveau pour agréger les données d'un joueur."""

    def __init__(self, api_key: str, platform: str = "euw1") -> None:
        self.platform = platform
        # Cluster régional déduit de la plateforme (défaut : europe).
        self.region = PLATFORM_TO_REGION.get(platform, "europe")
        self._lol = LolWatcher(api_key)
        self._riot = RiotWatcher(api_key)

    def get_player_summary(self, riot_id: str) -> PlayerSummary:
        """Agrège niveau, rang, winrate et dernières parties d'un Riot ID."""
        game_name, tag_line = parse_riot_id(riot_id)

        # 1) Account-V1 (cluster régional) : Riot ID -> PUUID.
        account = self._riot.account.by_riot_id(self.region, game_name, tag_line)
        puuid = account["puuid"]

        # 2) Summoner-V4 (plateforme) : niveau d'invocateur.
        summoner = self._lol.summoner.by_puuid(self.platform, puuid)
        level = int(summoner["summonerLevel"])

        # 3) League-V4 (plateforme) : rang de la file classée solo.
        rank = self._extract_solo_rank(self._lol.league.by_puuid(self.platform, puuid))

        # 4) Match-V5 (cluster régional) : dernières parties -> lignes de résumé.
        recent, winrate = self._recent_games(puuid)

        return PlayerSummary(
            game_name=account.get("gameName", game_name),
            tag_line=account.get("tagLine", tag_line),
            level=level,
            rank=rank,
            winrate=winrate,
            recent=recent,
        )

    @staticmethod
    def _extract_solo_rank(entries: list[dict]) -> str:
        """Extrait le rang RANKED_SOLO_5x5 depuis les entrées League-V4."""
        for entry in entries:
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                tier = entry.get("tier", "").capitalize()
                division = entry.get("rank", "")
                lp = entry.get("leaguePoints", 0)
                return f"{tier} {division} ({lp} LP)"
        return "Non classé"

    def _recent_games(self, puuid: str, count: int = 5) -> tuple[list[str], str]:
        """Renvoie les lignes de résumé des dernières parties et le winrate."""
        match_ids = self._lol.match.matchlist_by_puuid(self.region, puuid, count=count)

        lignes: list[str] = []
        victoires = 0
        for match_id in match_ids:
            match = self._lol.match.by_id(self.region, match_id)
            participant = self._find_participant(match, puuid)
            if participant is None:
                continue
            if participant.get("win"):
                victoires += 1
            lignes.append(self._format_game(participant))

        winrate = self._format_winrate(victoires, len(lignes))
        return lignes, winrate

    @staticmethod
    def _find_participant(match: dict, puuid: str) -> dict | None:
        """Retrouve le joueur dans info.participants via son PUUID."""
        for participant in match.get("info", {}).get("participants", []):
            if participant.get("puuid") == puuid:
                return participant
        return None

    @staticmethod
    def _format_game(participant: dict) -> str:
        """Formate une partie en « Victoire — Ahri (8/2/10) »."""
        issue = "Victoire" if participant.get("win") else "Défaite"
        champion = participant.get("championName", "?")
        k = participant.get("kills", 0)
        d = participant.get("deaths", 0)
        a = participant.get("assists", 0)
        return f"{issue} — {champion} ({k}/{d}/{a})"

    @staticmethod
    def _format_winrate(victoires: int, total: int) -> str:
        """Formate le winrate en pourcentage sur les parties analysées."""
        if total == 0:
            return "N/A"
        pourcentage = round(victoires / total * 100)
        return f"{pourcentage}% ({victoires}/{total})"


__all__ = [
    "ApiError",
    "PLATFORM_TO_REGION",
    "PlayerSummary",
    "RiotClient",
    "RiotIdError",
    "parse_riot_id",
]
