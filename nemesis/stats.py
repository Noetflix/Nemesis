"""Persistance et agrégation des statistiques d'activité du bot.

Toute l'activité (commandes, alertes de partie, notifications, paris) est journalisée
dans une base SQLite locale, puis agrégée en dataclasses prêtes à être servies en JSON
par le tableau de bord (voir ``statsweb.py`` et l'app bureau dans ``desktop/``).

Conçu multi-bots : chaque enregistrement porte le nom du bot (``bot``), ce qui permettra
d'agréger plusieurs applications dans le même tableau de bord plus tard.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

# Types d'évènements journalisés (colonne ``kind`` de la table ``events``).
KIND_COMMAND = "command"
KIND_COMMAND_ERROR = "command_error"
KIND_GAME_ALERT = "game_alert"
KIND_MATCH_NOTIF = "match_notif"
KIND_BET_RESULT = "bet_result"


@dataclass(frozen=True)
class StatPoint:
    """Un point de la courbe d'activité : un jour et son nombre de commandes."""

    date: str  # AAAA-MM-JJ
    count: int


@dataclass(frozen=True)
class CommandCount:
    """Nombre d'utilisations d'une commande."""

    name: str
    count: int


@dataclass(frozen=True)
class PlayerRecord:
    """Bilan d'un joueur suivi, dérivé des notifications de fin de partie."""

    name: str
    wins: int
    losses: int
    winrate: float  # 0..100
    last_seen: float | None  # epoch, dernière partie notifiée


@dataclass(frozen=True)
class BotActivity:
    """Bilan d'un bot pour la vue multi-bots."""

    bot: str
    commands: int
    games: int
    matches: int
    bets: int
    events: int
    last_active: float | None


@dataclass(frozen=True)
class RecentEvent:
    """Évènement récent, pour le flux d'activité du tableau de bord."""

    ts: float
    kind: str
    name: str | None
    win: bool | None
    detail: str | None


@dataclass(frozen=True)
class Overview:
    """Vue d'ensemble affichée en haut du tableau de bord."""

    bot: str
    generated_at: float
    started_at: float | None
    uptime_seconds: float | None
    total_runs: int
    commands_total: int
    commands_today: int
    games_tracked: int
    matches_notified: int
    bets_total: int
    bet_participants: int
    tracked_wins: int
    tracked_losses: int
    tracked_winrate: float  # 0..100


@dataclass
class StatsStore:
    """Accès à la base SQLite des statistiques (écriture bot, lecture API).

    Le bot et le serveur JSON vivent dans la même boucle asyncio (un seul thread) ;
    un verrou protège malgré tout les écritures par prudence.
    """

    conn: sqlite3.Connection
    bot_name: str = "nemesis"
    started_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def open(cls, db_path: str | Path, *, bot_name: str = "nemesis") -> StatsStore:
        """Ouvre (ou crée) la base et son schéma."""
        chemin = Path(db_path)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(chemin, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        store = cls(conn=conn, bot_name=bot_name)
        store._creer_schema()
        return store

    def _creer_schema(self) -> None:
        """Crée les tables et index si besoin (idempotent)."""
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id     INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts     REAL    NOT NULL,
                    bot    TEXT    NOT NULL,
                    kind   TEXT    NOT NULL,
                    name   TEXT,
                    win    INTEGER,
                    count  INTEGER,
                    detail TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
                CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

                CREATE TABLE IF NOT EXISTS runs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot        TEXT NOT NULL,
                    started_at REAL NOT NULL
                );
                """
            )
            self.conn.commit()

    def close(self) -> None:
        """Ferme la connexion SQLite."""
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ écriture

    def _insert(
        self,
        kind: str,
        *,
        name: str | None = None,
        win: bool | None = None,
        count: int | None = None,
        detail: str | None = None,
    ) -> None:
        """Journalise un évènement horodaté (ne lève jamais : la stat est secondaire)."""
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO events (ts, bot, kind, name, win, count, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        time.time(),
                        self.bot_name,
                        kind,
                        name,
                        None if win is None else int(win),
                        count,
                        detail,
                    ),
                )
                self.conn.commit()
        except sqlite3.Error:
            # Une stat perdue ne doit jamais faire tomber le bot.
            pass

    def mark_start(self) -> None:
        """Enregistre un démarrage du bot (pour le compteur de runs et l'uptime)."""
        self.started_at = time.time()
        try:
            with self._lock:
                self.conn.execute(
                    "INSERT INTO runs (bot, started_at) VALUES (?, ?)",
                    (self.bot_name, self.started_at),
                )
                self.conn.commit()
        except sqlite3.Error:
            pass

    def record_command(self, name: str) -> None:
        """Une commande a été exécutée avec succès."""
        self._insert(KIND_COMMAND, name=name)

    def record_command_error(self, name: str | None, error: str) -> None:
        """Une commande a échoué (erreur inattendue)."""
        self._insert(KIND_COMMAND_ERROR, name=name, detail=error[:500])

    def record_game_alert(self, riot_id: str, champion: str) -> None:
        """Une alerte « en game » a été postée."""
        self._insert(KIND_GAME_ALERT, name=riot_id, detail=champion)

    def record_match_notif(self, riot_id: str, win: bool) -> None:
        """Une fin de partie classée a été notifiée."""
        self._insert(KIND_MATCH_NOTIF, name=riot_id, win=win)

    def record_bet_result(self, game_id: str, win: bool, participants: int) -> None:
        """Un pari s'est clôturé (issue de la partie + nombre de parieurs)."""
        self._insert(KIND_BET_RESULT, name=game_id, win=win, count=participants)

    # ------------------------------------------------------------------ lecture

    def _count(self, kind: str, *, since: float | None = None) -> int:
        sql = "SELECT COUNT(*) FROM events WHERE kind = ?"
        params: list[object] = [kind]
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since)
        return int(self.conn.execute(sql, params).fetchone()[0])

    def overview(self) -> Overview:
        """Vue d'ensemble : compteurs globaux, uptime et winrate des joueurs suivis."""
        now = time.time()
        debut_jour = (
            datetime.now()
            .astimezone()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )

        total_runs = int(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        participants = self.conn.execute(
            "SELECT COALESCE(SUM(count), 0) FROM events WHERE kind = ?", (KIND_BET_RESULT,)
        ).fetchone()[0]

        wins = self._count_win(KIND_MATCH_NOTIF, win=True)
        losses = self._count_win(KIND_MATCH_NOTIF, win=False)
        total_parties = wins + losses
        winrate = (wins / total_parties * 100) if total_parties else 0.0

        return Overview(
            bot=self.bot_name,
            generated_at=now,
            started_at=self.started_at,
            uptime_seconds=(now - self.started_at) if self.started_at else None,
            total_runs=total_runs,
            commands_total=self._count(KIND_COMMAND),
            commands_today=self._count(KIND_COMMAND, since=debut_jour),
            games_tracked=self._count(KIND_GAME_ALERT),
            matches_notified=self._count(KIND_MATCH_NOTIF),
            bets_total=self._count(KIND_BET_RESULT),
            bet_participants=int(participants),
            tracked_wins=wins,
            tracked_losses=losses,
            tracked_winrate=round(winrate, 1),
        )

    def _count_win(self, kind: str, *, win: bool) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE kind = ? AND win = ?",
                (kind, int(win)),
            ).fetchone()[0]
        )

    def commands_breakdown(self) -> list[CommandCount]:
        """Répartition des commandes par nom, de la plus à la moins utilisée."""
        rows = self.conn.execute(
            "SELECT name, COUNT(*) AS n FROM events WHERE kind = ? AND name IS NOT NULL "
            "GROUP BY name ORDER BY n DESC",
            (KIND_COMMAND,),
        ).fetchall()
        return [CommandCount(name=r["name"], count=int(r["n"])) for r in rows]

    def activity_timeline(self, *, days: int = 14) -> list[StatPoint]:
        """Nombre de commandes par jour sur ``days`` jours (trous comblés à 0)."""
        aujourd_hui = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        depuis = (aujourd_hui - timedelta(days=days - 1)).timestamp()
        rows = self.conn.execute(
            "SELECT ts FROM events WHERE kind = ? AND ts >= ?",
            (KIND_COMMAND, depuis),
        ).fetchall()

        compteur: dict[str, int] = {}
        for row in rows:
            jour = datetime.fromtimestamp(row["ts"]).astimezone().strftime("%Y-%m-%d")
            compteur[jour] = compteur.get(jour, 0) + 1

        points: list[StatPoint] = []
        for i in range(days):
            jour = (aujourd_hui - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
            points.append(StatPoint(date=jour, count=compteur.get(jour, 0)))
        return points

    def players(self) -> list[PlayerRecord]:
        """Bilan V/D par joueur suivi, dérivé des notifications de fin de partie."""
        rows = self.conn.execute(
            "SELECT name, "
            "  SUM(CASE WHEN win = 1 THEN 1 ELSE 0 END) AS wins, "
            "  SUM(CASE WHEN win = 0 THEN 1 ELSE 0 END) AS losses, "
            "  MAX(ts) AS last_seen "
            "FROM events WHERE kind = ? AND name IS NOT NULL "
            "GROUP BY name ORDER BY (wins + losses) DESC",
            (KIND_MATCH_NOTIF,),
        ).fetchall()
        joueurs: list[PlayerRecord] = []
        for r in rows:
            wins, losses = int(r["wins"]), int(r["losses"])
            total = wins + losses
            joueurs.append(
                PlayerRecord(
                    name=r["name"],
                    wins=wins,
                    losses=losses,
                    winrate=round(wins / total * 100, 1) if total else 0.0,
                    last_seen=r["last_seen"],
                )
            )
        return joueurs

    def bots(self) -> list[BotActivity]:
        """Bilan par bot (commandes, games, parties, paris) pour la vue multi-bots."""
        rows = self.conn.execute(
            "SELECT bot, "
            "  SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS commands, "
            "  SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS games, "
            "  SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS matches, "
            "  SUM(CASE WHEN kind = ? THEN 1 ELSE 0 END) AS bets, "
            "  COUNT(*) AS events, "
            "  MAX(ts) AS last_active "
            "FROM events GROUP BY bot ORDER BY events DESC",
            (KIND_COMMAND, KIND_GAME_ALERT, KIND_MATCH_NOTIF, KIND_BET_RESULT),
        ).fetchall()
        return [
            BotActivity(
                bot=r["bot"],
                commands=int(r["commands"] or 0),
                games=int(r["games"] or 0),
                matches=int(r["matches"] or 0),
                bets=int(r["bets"] or 0),
                events=int(r["events"] or 0),
                last_active=r["last_active"],
            )
            for r in rows
        ]

    def recent_events(self, *, limit: int = 20) -> list[RecentEvent]:
        """Derniers évènements journalisés, du plus récent au plus ancien."""
        rows = self.conn.execute(
            "SELECT ts, kind, name, win, detail FROM events ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            RecentEvent(
                ts=r["ts"],
                kind=r["kind"],
                name=r["name"],
                win=None if r["win"] is None else bool(r["win"]),
                detail=r["detail"],
            )
            for r in rows
        ]
