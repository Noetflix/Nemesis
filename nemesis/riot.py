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

# Files classées susceptibles de déclencher une notification de fin de partie.
RANKED_QUEUES: frozenset[int] = frozenset({420, 440})

# Nom lisible du rôle (teamPosition renvoyé par Match-V5).
ROLE_NAMES: dict[str, str] = {
    "TOP": "Top",
    "JUNGLE": "Jungle",
    "MIDDLE": "Mid",
    "BOTTOM": "ADC",
    "UTILITY": "Support",
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

    @property
    def ladder_points(self) -> int:
        """LP cumulés sur toute l'échelle (100 LP par division, 400 par palier).

        Permet de calculer un gain/perte de LP même à travers une montée ou une chute
        de division/palier. Non classé = 0.
        """
        if not self.is_ranked:
            return 0
        tier = _TIER_ORDER.get(self.tier.upper(), 0)
        division = _DIVISION_ORDER.get(self.division.upper(), 0)
        return tier * 400 + division * 100 + self.league_points


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
class MatchDetail:
    """Statistiques détaillées d'une partie terminée (notification de fin de game)."""

    match_id: str
    game_name: str
    tag_line: str
    champion: str
    champ_level: int
    kills: int
    deaths: int
    assists: int
    win: bool
    queue_id: int
    duration_s: int
    cs: int
    gold: int
    damage_champions: int
    damage_taken: int
    vision_score: int
    wards_placed: int
    largest_multi_kill: int
    double_kills: int
    triple_kills: int
    quadra_kills: int
    penta_kills: int
    team_position: str
    kill_participation: float | None  # 0.0–1.0, ou None si l'API ne le fournit pas.
    ddragon_version: str

    @property
    def kda_ratio(self) -> float:
        """Ratio (K + A) / D ; une mort minimum pour éviter la division par zéro."""
        return (self.kills + self.assists) / max(self.deaths, 1)

    @property
    def queue_name(self) -> str:
        """Nom lisible de la file de jeu."""
        return QUEUE_NAMES.get(self.queue_id, "Partie personnalisée")

    @property
    def role_name(self) -> str:
        """Rôle lisible (Top, Jungle, Mid, ADC, Support), vide si inconnu."""
        return ROLE_NAMES.get(self.team_position.upper(), "")

    @property
    def cs_per_min(self) -> float:
        """Sbires par minute (indicateur de farm)."""
        minutes = self.duration_s / 60
        return self.cs / minutes if minutes else 0.0

    @property
    def gold_per_min(self) -> float:
        """Or par minute (indicateur d'économie)."""
        minutes = self.duration_s / 60
        return self.gold / minutes if minutes else 0.0

    @property
    def champion_icon_url(self) -> str:
        """URL Data Dragon de l'icône du champion joué."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/champion/{self.champion}.png"
        )

    @property
    def multikill_label(self) -> str | None:
        """Plus haut multi-kill notable (Penta > Quadra > Triple > Double), ou None."""
        if self.penta_kills:
            return "PENTAKILL"
        if self.quadra_kills:
            return "Quadrakill"
        if self.triple_kills:
            return "Triplekill"
        if self.double_kills:
            return "Doublekill"
        return None


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


@dataclass(frozen=True)
class ChampionMastery:
    """Maîtrise d'un champion pour un joueur (commande !maitrise)."""

    champion: str
    level: int
    points: int
    last_play_ms: int  # date de dernière partie (epoch en millisecondes).
    ddragon_version: str

    @property
    def champion_icon_url(self) -> str:
        """URL Data Dragon de l'icône du champion."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/champion/{self.champion}.png"
        )


@dataclass(frozen=True)
class MasterySummary:
    """Identité d'un joueur + ses champions les plus maîtrisés."""

    game_name: str
    tag_line: str
    profile_icon_id: int
    ddragon_version: str
    masteries: list[ChampionMastery]

    @property
    def profile_icon_url(self) -> str:
        """URL Data Dragon de l'icône d'invocateur."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/profileicon/{self.profile_icon_id}.png"
        )


@dataclass(frozen=True)
class LiveGame:
    """Partie en cours d'un joueur (alerte « en game », Spectator-V5)."""

    game_id: str
    queue_id: int
    champion: str
    ddragon_version: str
    start_ms: int

    @property
    def is_ranked(self) -> bool:
        """Vrai si la partie est une file classée (solo/duo ou flex)."""
        return self.queue_id in RANKED_QUEUES

    @property
    def queue_name(self) -> str:
        """Nom lisible de la file de jeu."""
        return QUEUE_NAMES.get(self.queue_id, "Partie personnalisée")

    @property
    def champion_icon_url(self) -> str:
        """URL Data Dragon de l'icône du champion joué."""
        return (
            f"https://ddragon.leagueoflegends.com/cdn/{self.ddragon_version}"
            f"/img/champion/{self.champion}.png"
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
        # Correspondance championId (numérique) -> nom, mise en cache.
        self._champion_names: dict[int, str] | None = None

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

    def resolve_puuid(self, riot_id: str) -> str:
        """Résout un Riot ID (Pseudo#TAG) en PUUID via Account-V1 (cluster régional)."""
        game_name, tag_line = parse_riot_id(riot_id)
        account = self._riot.account.by_riot_id(self.region, game_name, tag_line)
        return account["puuid"]

    def latest_ranked_match_id(self, puuid: str) -> str | None:
        """ID de la dernière partie classée (solo ou flex) du joueur, ou None."""
        ids = self._lol.match.matchlist_by_puuid(self.region, puuid, count=1, type="ranked")
        return ids[0] if ids else None

    def match_detail(self, match_id: str, puuid: str) -> MatchDetail | None:
        """Construit le MatchDetail d'une partie pour ce joueur.

        Renvoie None si la partie n'est pas classée (solo/flex) ou si le joueur est absent.
        """
        match = self._lol.match.by_id(self.region, match_id)
        info = match.get("info", {})
        queue_id = int(info.get("queueId", 0))
        if queue_id not in RANKED_QUEUES:
            return None
        participant = self._find_participant(match, puuid)
        if participant is None:
            return None

        challenges = participant.get("challenges") or {}
        kp = challenges.get("killParticipation")
        cs = int(participant.get("totalMinionsKilled", 0)) + int(
            participant.get("neutralMinionsKilled", 0)
        )
        return MatchDetail(
            match_id=match_id,
            game_name=participant.get("riotIdGameName") or participant.get("summonerName", "?"),
            tag_line=participant.get("riotIdTagline", ""),
            champion=participant.get("championName", "?"),
            champ_level=int(participant.get("champLevel", 0)),
            kills=int(participant.get("kills", 0)),
            deaths=int(participant.get("deaths", 0)),
            assists=int(participant.get("assists", 0)),
            win=bool(participant.get("win")),
            queue_id=queue_id,
            duration_s=int(info.get("gameDuration", 0)),
            cs=cs,
            gold=int(participant.get("goldEarned", 0)),
            damage_champions=int(participant.get("totalDamageDealtToChampions", 0)),
            damage_taken=int(participant.get("totalDamageTaken", 0)),
            vision_score=int(participant.get("visionScore", 0)),
            wards_placed=int(participant.get("wardsPlaced", 0)),
            largest_multi_kill=int(participant.get("largestMultiKill", 0)),
            double_kills=int(participant.get("doubleKills", 0)),
            triple_kills=int(participant.get("tripleKills", 0)),
            quadra_kills=int(participant.get("quadraKills", 0)),
            penta_kills=int(participant.get("pentaKills", 0)),
            team_position=participant.get("teamPosition", ""),
            kill_participation=float(kp) if kp is not None else None,
            ddragon_version=self._latest_ddragon_version(),
        )

    def current_rank_for_queue(self, puuid: str, queue_id: int) -> RankInfo:
        """Rang actuel du joueur dans la file de la partie (Flex si 440, sinon Solo/Duo)."""
        queue_type = "RANKED_FLEX_SR" if queue_id == 440 else "RANKED_SOLO_5x5"
        for entry in self._lol.league.by_puuid(self.platform, puuid):
            if entry.get("queueType") == queue_type:
                return self._rank_from_entry(entry)
        return RankInfo(tier="", division="", league_points=0, wins=0, losses=0)

    def ranks_all_queues(self, puuid: str) -> dict[int, RankInfo]:
        """Rangs Solo/Duo (420) et Flex (440) en un seul appel League-V4.

        Sert à mémoriser le rang « avant partie » pour calculer le gain/perte de LP.
        Les files absentes sont renvoyées comme non classées.
        """
        rangs: dict[int, RankInfo] = {
            420: RankInfo(tier="", division="", league_points=0, wins=0, losses=0),
            440: RankInfo(tier="", division="", league_points=0, wins=0, losses=0),
        }
        for entry in self._lol.league.by_puuid(self.platform, puuid):
            if entry.get("queueType") == "RANKED_SOLO_5x5":
                rangs[420] = self._rank_from_entry(entry)
            elif entry.get("queueType") == "RANKED_FLEX_SR":
                rangs[440] = self._rank_from_entry(entry)
        return rangs

    @staticmethod
    def _rank_from_entry(entry: dict) -> RankInfo:
        """Construit un RankInfo depuis une entrée League-V4."""
        return RankInfo(
            tier=entry.get("tier", ""),
            division=entry.get("rank", ""),
            league_points=int(entry.get("leaguePoints", 0)),
            wins=int(entry.get("wins", 0)),
            losses=int(entry.get("losses", 0)),
        )

    def get_champion_masteries(self, riot_id: str, count: int = 5) -> MasterySummary:
        """Champions les plus maîtrisés d'un joueur (Champion-Mastery-V4, plateforme)."""
        game_name, tag_line = parse_riot_id(riot_id)

        # 1) Account-V1 (cluster régional) : Riot ID -> PUUID.
        account = self._riot.account.by_riot_id(self.region, game_name, tag_line)
        puuid = account["puuid"]

        # 2) Summoner-V4 (plateforme) : icône d'invocateur.
        summoner = self._lol.summoner.by_puuid(self.platform, puuid)

        # 3) Champion-Mastery-V4 (plateforme) : top champions par points de maîtrise.
        entries = self._lol.champion_mastery.top_by_puuid(self.platform, puuid, count=count)
        noms = self._noms_champions()
        version = self._latest_ddragon_version()
        masteries = [
            ChampionMastery(
                champion=noms.get(int(entry.get("championId", 0)), "?"),
                level=int(entry.get("championLevel", 0)),
                points=int(entry.get("championPoints", 0)),
                last_play_ms=int(entry.get("lastPlayTime", 0)),
                ddragon_version=version,
            )
            for entry in entries
        ]
        return MasterySummary(
            game_name=account.get("gameName", game_name),
            tag_line=account.get("tagLine", tag_line),
            profile_icon_id=int(summoner.get("profileIconId", 0)),
            ddragon_version=version,
            masteries=masteries,
        )

    def active_game(self, puuid: str) -> LiveGame | None:
        """Partie en cours du joueur (Spectator-V5, plateforme), ou None s'il n'est pas en jeu.

        Un 404 signifie « pas en partie » ; les autres erreurs API sont propagées.
        """
        try:
            game = self._lol.spectator.by_summoner(self.platform, puuid)
        except ApiError as exc:
            if exc.response.status_code == 404:
                return None
            raise

        participant = next(
            (p for p in game.get("participants", []) if p.get("puuid") == puuid), None
        )
        champion = "?"
        if participant is not None:
            champion = self._noms_champions().get(int(participant.get("championId", 0)), "?")
        return LiveGame(
            game_id=str(game.get("gameId", "")),
            queue_id=int(game.get("gameQueueConfigId", 0)),
            champion=champion,
            ddragon_version=self._latest_ddragon_version(),
            start_ms=int(game.get("gameStartTime", 0)),
        )

    def _noms_champions(self) -> dict[int, str]:
        """Correspondance championId -> nom (via Data Dragon), mise en cache."""
        if self._champion_names is None:
            try:
                data = self._lol.data_dragon.champions(self._latest_ddragon_version())["data"]
                self._champion_names = {int(champ["key"]): champ["id"] for champ in data.values()}
            except Exception:  # noqa: BLE001 — sans la table, on affiche « ? » plutôt que crasher.
                self._champion_names = {}
        return self._champion_names

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
    "RANKED_QUEUES",
    "ROLE_NAMES",
    "ChampionMastery",
    "LiveGame",
    "MasterySummary",
    "MatchDetail",
    "PlayerRank",
    "PlayerSummary",
    "QUEUE_NAMES",
    "RankInfo",
    "RecentGame",
    "RiotClient",
    "RiotIdError",
    "parse_riot_id",
]
