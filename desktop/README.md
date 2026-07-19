# Némésis — App bureau (tableau de bord des stats)

Application Windows qui s'ouvre depuis le bureau (icône Némésis) et affiche les
statistiques du bot : commandes utilisées, activité, alertes en game, paris et
winrate des joueurs suivis.

## Comment ça marche

```
bot.py  ──enregistre──▶  data/stats.db  ──sert JSON──▶  app bureau (PyWebView)
(Discord)                (SQLite)          (aiohttp)      cette fenêtre
```

- Le bot journalise son activité dans une base SQLite (`nemesis/stats.py`).
- Il expose un petit serveur JSON local (`nemesis/statsweb.py`) sur
  `http://127.0.0.1:8787` (configurable via `.env`, voir `STATS_*`).
- L'app bureau (`app.py` + `web/`) est un simple client qui interroge cette API et
  dessine le tableau de bord. **Elle ne touche jamais directement à la base.**

## Prévisualiser sans lancer le bot

Le serveur de démo remplit une base factice et sert l'API :

```bash
# terminal 1 — données de démonstration
uv run --group desktop python desktop/serve_demo.py

# terminal 2 — la fenêtre
uv run --group desktop python desktop/app.py
```

## Utiliser avec le vrai bot

1. Lance le bot normalement : `uv run python -m nemesis`
   (le serveur de stats démarre automatiquement, sauf si `STATS_ENABLED=0`).
2. Ouvre l'app : `uv run --group desktop python desktop/app.py`.

## Construire l'exécutable `.exe` (icône sur le bureau)

```bash
uv run --group desktop python desktop/build.py
```

Produit `desktop/dist/Nemesis-Stats.exe`, double-cliquable et pourvu de l'icône
Némésis. Clic droit dessus → *Envoyer vers* → *Bureau (créer un raccourci)*.

## Viser un serveur distant (VPS)

L'app lit la variable d'environnement `NEMESIS_STATS_URL`. Quand le bot tournera sur
un VPS, il suffit de la définir avant de lancer l'app (ou dans le raccourci) :

```bash
set NEMESIS_STATS_URL=https://mon-vps.exemple
uv run --group desktop python desktop/app.py
```

Côté bot/VPS, mettre `STATS_API_HOST=0.0.0.0` (idéalement derrière un reverse proxy
HTTPS) pour rendre l'API joignable depuis l'extérieur.
