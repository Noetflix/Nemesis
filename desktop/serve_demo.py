"""Sert des statistiques de démonstration pour prévisualiser l'app bureau.

Alimente une base temporaire avec des données réalistes puis démarre l'API locale,
sans avoir besoin de lancer le bot Discord. Idéal pour découvrir le tableau de bord.

    uv run --group desktop python desktop/serve_demo.py
    # puis, dans un autre terminal :
    uv run --group desktop python desktop/app.py
"""

from __future__ import annotations

import asyncio
import random
import sys
import time
from pathlib import Path

# Rendre le package `nemesis` importable quand on lance ce script directement.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nemesis.stats import KIND_COMMAND, StatsStore  # noqa: E402
from nemesis.statsweb import start_stats_server  # noqa: E402

HOST, PORT = "127.0.0.1", 8787
JOUEURS = ["OT Noetflix#T1WIN", "OT Néons#KCORP", "OT BaGeR#BGR", "Rat Yote#5234"]
CHAMPIONS = ["Yasuo", "Ahri", "Lee Sin", "Jinx", "Thresh", "Viego"]


def seed(store: StatsStore) -> None:
    """Injecte ~2 semaines d'activité factice directement dans la base."""
    now = time.time()
    store.mark_start()
    store.started_at = now - (3 * 86400 + 7 * 3600)  # uptime affiché ~3j 7h

    # Commandes réparties sur 14 jours (insertion directe pour dater le passé).
    noms = ["stats", "classement", "derniere", "maitrise", "versus", "help"]
    poids = [40, 22, 14, 10, 8, 6]
    with store._lock:  # accès direct assumé : script de démo uniquement
        for j in range(14):
            ts_jour = now - j * 86400
            for _ in range(random.randint(3, 16)):
                nom = random.choices(noms, weights=poids)[0]
                store.conn.execute(
                    "INSERT INTO events (ts, bot, kind, name) VALUES (?, ?, ?, ?)",
                    (ts_jour - random.randint(0, 80000), store.bot_name, KIND_COMMAND, nom),
                )
        store.conn.commit()

    for _ in range(9):
        j = random.choice(JOUEURS)
        store.record_game_alert(j, random.choice(CHAMPIONS))
        store.record_match_notif(j, random.random() < 0.55)
        if random.random() < 0.6:
            store.record_bet_result(
                str(random.randint(1000, 9999)), random.random() < 0.5, random.randint(0, 6)
            )


async def main() -> None:
    db = Path(__file__).resolve().parent / "demo_stats.db"
    if db.exists():
        db.unlink()
    store = StatsStore.open(db, bot_name="nemesis")
    seed(store)
    await start_stats_server(store, host=HOST, port=PORT)
    print(f"Démo servie sur http://{HOST}:{PORT}  —  Ctrl+C pour arrêter.")
    print("Ouvre l'app :  uv run --group desktop python desktop/app.py")
    await asyncio.Event().wait()  # tourne jusqu'à interruption


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
