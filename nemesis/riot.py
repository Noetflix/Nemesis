"""Client de l'API Riot pour League of Legends.

Flux MODERNE (ne jamais utiliser les endpoints par nom d'invocateur, obsolètes) :

    Riot ID (Pseudo#TAG) --Account-V1--> PUUID
    PUUID                --Summoner-V4--> niveau + icône
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

# Noms lisibles des files de jeu (queueId renvoyé par Match-V5).
QUEUE_NAMES: dict[int, str] = {
    400: "Normale Draft",
    420: "Classée Solo/Duo",
    430: "Normale Blind",
    440: "Classée Flexible",
    450: "ARAM",
    490: "Normale (Quickplay)",
    700: "Clash",
    720: "ARAM Clash",
    900: "URF",
    1020: "One for All",
    1700: "Arena",
    1710: "Arena",
}

# Version Data Dragon de secours si l'appel réseau échoue (images non critiques).
_DDRAGON_FALLBACK_VERSION = "15.13.1"

# Ordre des paliers et divisions pour classer les joueurs entre eux.
_TIER_ORDER: dict[str, int] = {
    "IRON": 0,
    "BRONZE": 1,
    "SILVER": 2,
    "GOLD": 3,
    "PLATINUM": 4,
    "EMERALD": 5,
    "DIAMOND": 6,
    "MASTER": 7,
    "GRANDMASTER": 8,
    "CHALLENGER": 9,
}
_DIVISION_ORDER: dict[str, int] = {"IV": 0, "III": 1, "II": 2, "I": 3}


class RiotIdError(ValueError):
    """Riot ID mal formé (le « # » séparateur est absent)."""


@dataclass(frozen=True)
class RankInfo:
    """Rang classé d'un joueur en file solo/duo."""

    tier: str  # « GOLD », ou « » si non classé.
    division: str  # « IV », vide pour Master et au-dessus.
    league_points: int
    wins: int
    losses: int

    @property
    def is_ranked(self) -> bool:
        """Vrai si le joueur possède un rang en solo/duo."""
        return bool(self.tier)

    @property
    def total_games(self) -> int:
        """Nombre de parties classées jouées cette saison."""
        return self.wins + self.losses

    @property
    def winrate(self) -> float | None:
        """Winrate classé en pourcentage, ou None sans partie jouée."""
        if self.total_games == 0:
            return None
        return self.wins / self.total_games * 100

    @property
    def score(self) -> int:
        """Score numérique croissant pour trier les joueurs (non classé = -1)."""
        if not self.is_ranked:
            return -1
        tier = _TIER_ORDER.get(self.tier.upper(), 0)
        division = _DIVISION_ORDER.get(self.division.upper(), 0)
        # Palier dominant, puis division, puis LP : aucun chevauchement possible.
        return tier * 100_000 + division * 1_000 + self.league_points


@dataclass(frozen=True)
class RecentGame:
    """Résumé d'une partie récente pour l'affichage."""

    champion: str
    kills: int
    deaths: int
    assists: int
    win: bool
    queue_id: int
    duration_s: int
    cs: int

    @property
    def kda_ratio(self) -> float:
        """Ratio (K + A) / D ; une seule mort minimum pour éviter la division par zéro."""
        return (self.kills + self.assists) / max(self.deaths, 1)

    @property
    def queue_name(self) -> str:
        """Nom lisible de la file de jeu."""
        return QUEUE_NAMES.get(self.queue_id, "Partie personnalisée")

    @property
    def cs_per_min(self) -> float:
        """Sbires par minute (indicateur de farm)."""
        minutes = self.duration_s / 60
        return self.cs / minutes if minutes else 0.0


@dataclass(frozen=True)
class PlayerSummary:
    """Résumé agrégé des statistiques d'un joueur."""

    game_name: str
    tag_line: str
    level: int
    profile_icon_id: int
    ddragon_version: str
    rank: RankInfo
    recent: list[RecentGame]

    @property
    def profile_icon_url(self) -> str:
        """URL Data Dragon de l'icône d'invocateur (miniature de l'embed)."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/profileicon/{self.profile_icon_id}.png"
        )

    @property
    def recent_wins(self) -> int:
        """Nombre de victoires parmi les parties récentes."""
        return sum(1 for game in self.recent if game.win)


@dataclass(frozen=True)
class PlayerRank:
    """Résumé léger d'un joueur pour le classement (sans les parties récentes)."""

    game_name: str
    tag_line: str
    level: int
    profile_icon_id: int
    ddragon_version: str
    rank: RankInfo

    @property
    def profile_icon_url(self) -> str:
        """URL Data Dragon de l'icône d'invocateur."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/profileicon/{self.profile_icon_id}.png"
        )


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
        # Version Data Dragon mise en cache après le premier appel.
        self._ddragon_version: str | None = None

    def get_player_summary(self, riot_id: str) -> PlayerSummary:
        """Agrège niveau, rang, winrate et dernières parties d'un Riot ID."""
        game_name, tag_line = parse_riot_id(riot_id)

        # 1) Account-V1 (cluster régional) : Riot ID -> PUUID.
        account = self._riot.account.by_riot_id(self.region, game_name, tag_line)
        puuid = account["puuid"]

        # 2) Summoner-V4 (plateforme) : niveau et icône d'invocateur.
        summoner = self._lol.summoner.by_puuid(self.platform, puuid)
        level = int(summoner["summonerLevel"])
        profile_icon_id = int(summoner.get("profileIconId", 0))

        # 3) League-V4 (plateforme) : rang de la file classée solo.
        rank = self._extract_solo_rank(self._lol.league.by_puuid(self.platform, puuid))

        # 4) Match-V5 (cluster régional) : dernières parties -> objets RecentGame.
        recent = self._recent_games(puuid)

        return PlayerSummary(
            game_name=account.get("gameName", game_name),
            tag_line=account.get("tagLine", tag_line),
            level=level,
            profile_icon_id=profile_icon_id,
            ddragon_version=self._latest_ddragon_version(),
            rank=rank,
            recent=recent,
        )

    def get_rank(self, riot_id: str) -> PlayerRank:
        """Récupère niveau, icône et rang classé d'un joueur (léger, pour le classement).

        Ne fait pas d'appel Match-V5 : idéal pour interroger plusieurs joueurs à la suite.
        """
        game_name, tag_line = parse_riot_id(riot_id)

        # 1) Account-V1 (cluster régional) : Riot ID -> PUUID.
        account = self._riot.account.by_riot_id(self.region, game_name, tag_line)
        puuid = account["puuid"]

        # 2) Summoner-V4 (plateforme) : niveau et icône.
        summoner = self._lol.summoner.by_puuid(self.platform, puuid)

        # 3) League-V4 (plateforme) : rang de la file classée solo.
        rank = self._extract_solo_rank(self._lol.league.by_puuid(self.platform, puuid))

        return PlayerRank(
            game_name=account.get("gameName", game_name),
            tag_line=account.get("tagLine", tag_line),
            level=int(summoner["summonerLevel"]),
            profile_icon_id=int(summoner.get("profileIconId", 0)),
            ddragon_version=self._latest_ddragon_version(),
            rank=rank,
        )

    def _latest_ddragon_version(self) -> str:
        """Dernière version Data Dragon (mise en cache) pour construire les URLs d'images."""
        if self._ddragon_version is None:
            try:
                self._ddragon_version = self._lol.data_dragon.versions_all()[0]
            except Exception:  # noqa: BLE001 — images non critiques, on dégrade proprement.
                self._ddragon_version = _DDRAGON_FALLBACK_VERSION
        return self._ddragon_version

    @staticmethod
    def _extract_solo_rank(entries: list[dict]) -> RankInfo:
        """Extrait le rang RANKED_SOLO_5x5 depuis les entrées League-V4."""
        for entry in entries:
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                return RankInfo(
                    tier=entry.get("tier", ""),
                    division=entry.get("rank", ""),
                    league_points=int(entry.get("leaguePoints", 0)),
                    wins=int(entry.get("wins", 0)),
                    losses=int(entry.get("losses", 0)),
                )
        return RankInfo(tier="", division="", league_points=0, wins=0, losses=0)

    def _recent_games(self, puuid: str, count: int = 5) -> list[RecentGame]:
        """Renvoie les dernières parties du joueur sous forme d'objets RecentGame."""
        match_ids = self._lol.match.matchlist_by_puuid(self.region, puuid, count=count)

        parties: list[RecentGame] = []
        for match_id in match_ids:
            match = self._lol.match.by_id(self.region, match_id)
            participant = self._find_participant(match, puuid)
            if participant is None:
                continue
            parties.append(self._build_game(participant, match.get("info", {})))
        return parties

    @staticmethod
    def _find_participant(match: dict, puuid: str) -> dict | None:
        """Retrouve le joueur dans info.participants via son PUUID."""
        for participant in match.get("info", {}).get("participants", []):
            if participant.get("puuid") == puuid:
                return participant
        return None

    @staticmethod
    def _build_game(participant: dict, info: dict) -> RecentGame:
        """Construit un RecentGame depuis un participant et les infos de partie."""
        cs = int(participant.get("totalMinionsKilled", 0)) + int(
            participant.get("neutralMinionsKilled", 0)
        )
        return RecentGame(
            champion=participant.get("championName", "?"),
            kills=int(participant.get("kills", 0)),
            deaths=int(participant.get("deaths", 0)),
            assists=int(participant.get("assists", 0)),
            win=bool(participant.get("win")),
            queue_id=int(info.get("queueId", 0)),
            duration_s=int(info.get("gameDuration", 0)),
            cs=cs,
        )


__all__ = [
    "ApiError",
    "PLATFORM_TO_REGION",
    "PlayerRank",
    "PlayerSummary",
    "QUEUE_NAMES",
    "RankInfo",
    "RecentGame",
    "RiotClient",
    "RiotIdError",
    "parse_riot_id",
]
