# Némésis

Bot Discord de statistiques **League of Legends** (Python 3.14, discord.py + riotwatcher).
Application gérée avec **uv** (pas de publication de paquet).

## Modules (`nemesis/`)

- `__init__.py` — version du package.
- `__main__.py` — entrée `python -m nemesis`, appelle `bot.main()`.
- `config.py` — dataclass gelée `Config` + `load_config()` (secrets depuis `.env`).
- `riot.py` — client de l'API Riot ; agrège les données en dataclasses (`PlayerSummary`).
- `bot.py` — bot Discord, commandes, embeds, traduction des erreurs API.
- `stats.py` — persistance SQLite de l'activité du bot + agrégats (dataclasses).
- `statsweb.py` — petit serveur JSON (aiohttp) exposant les stats, démarré par `bot.py`.

**Règle d'architecture :** toute la logique métier / API vit dans `riot.py` (et la
persistance dans `stats.py`) et renvoie des dataclasses. `bot.py` ne fait qu'orchestrer
Discord (commandes, embeds, gestion d'erreurs) et brancher la journalisation des stats.

## App bureau (`desktop/`)

Application Windows (PyWebView) affichant un tableau de bord des stats. Client HTTP pur
qui interroge le serveur JSON du bot (`http://127.0.0.1:8787` en local, `NEMESIS_STATS_URL`
pour un VPS) — il ne touche jamais la base directement. Voir `desktop/README.md`.

## Commandes

```bash
uv sync                     # installer les dépendances
uv run python -m nemesis    # lancer le bot
uv run ruff format .        # formatage
uv run ruff check --fix     # lint + corrections
uv add <paquet>             # ajouter une dépendance (jamais pip)

# App bureau (tableau de bord des stats)
uv run --group desktop python desktop/serve_demo.py  # API de démo (données factices)
uv run --group desktop python desktop/app.py         # ouvrir la fenêtre
uv run --group desktop python desktop/build.py       # construire le .exe (icône Némésis)
```

## Conventions

- `from __future__ import annotations` en tête de chaque module ; type hints systématiques.
- Commentaires et docstrings **en français**, concis.
- Objets de données = **dataclasses**.
- Secrets **uniquement** via `.env` (jamais committés, jamais en dur).

## Les 3 pièges à ne jamais oublier

1. **Double routing Riot** — la *plateforme* (euw1, na1, kr…) sert à Summoner-V4 et
   League-V4 ; le *cluster régional* (europe, americas, asia, sea) sert à Account-V1 et
   Match-V5. Voir `PLATFORM_TO_REGION` dans `riot.py`.
2. **Clé Riot dev = 24 h** — un code **403** signifie clé expirée : la régénérer sur
   developer.riotgames.com.
3. **Intent Message Content** — à activer dans le portail développeur Discord, sinon le bot
   ne lit pas les commandes texte.

Les procédures détaillées sont dans les skills (`.claude/skills/`), pas ici.
