"""Petit serveur JSON exposant les statistiques du bot au tableau de bord bureau.

Tourne dans la boucle asyncio du bot (démarré depuis ``bot.py``). L'app bureau
(``desktop/``) le consomme via HTTP. En local il écoute sur 127.0.0.1 ; sur un VPS,
passer ``STATS_API_HOST=0.0.0.0`` pour l'exposer (idéalement derrière un reverse proxy).
"""

from __future__ import annotations

import logging
from dataclasses import asdict

from aiohttp import web

from nemesis.stats import StatsStore

logger = logging.getLogger("nemesis")


@web.middleware
async def _cors_middleware(request: web.Request, handler: web.Handler) -> web.StreamResponse:
    """Autorise l'app bureau (origine file://) à interroger l'API."""
    if request.method == "OPTIONS":
        response: web.StreamResponse = web.Response()
    else:
        response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    return response


def create_stats_app(store: StatsStore) -> web.Application:
    """Construit l'application aiohttp et ses routes JSON."""
    app = web.Application(middlewares=[_cors_middleware])

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "bot": store.bot_name})

    async def overview(_: web.Request) -> web.Response:
        return web.json_response(asdict(store.overview()))

    async def commands(_: web.Request) -> web.Response:
        return web.json_response([asdict(c) for c in store.commands_breakdown()])

    async def activity(request: web.Request) -> web.Response:
        days = _int_query(request, "days", defaut=14, mini=1, maxi=90)
        return web.json_response([asdict(p) for p in store.activity_timeline(days=days)])

    async def players(_: web.Request) -> web.Response:
        return web.json_response([asdict(p) for p in store.players()])

    async def bots(_: web.Request) -> web.Response:
        return web.json_response([asdict(b) for b in store.bots()])

    async def events(request: web.Request) -> web.Response:
        limit = _int_query(request, "limit", defaut=20, mini=1, maxi=200)
        return web.json_response([asdict(e) for e in store.recent_events(limit=limit)])

    app.add_routes(
        [
            web.get("/api/health", health),
            web.get("/api/overview", overview),
            web.get("/api/commands", commands),
            web.get("/api/activity", activity),
            web.get("/api/players", players),
            web.get("/api/bots", bots),
            web.get("/api/events", events),
        ]
    )
    return app


def _int_query(request: web.Request, cle: str, *, defaut: int, mini: int, maxi: int) -> int:
    """Lit un entier borné depuis la query string, avec repli sur ``defaut``."""
    brut = request.query.get(cle)
    if brut is None or not brut.strip().lstrip("-").isdigit():
        return defaut
    return max(mini, min(maxi, int(brut)))


async def start_stats_server(store: StatsStore, *, host: str, port: int) -> web.AppRunner:
    """Démarre le serveur dans la boucle courante et renvoie le runner (à garder en vie)."""
    runner = web.AppRunner(create_stats_app(store))
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    logger.info("Serveur de stats démarré sur http://%s:%s (API /api/*).", host, port)
    return runner
