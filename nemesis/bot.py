"""Bot Discord Némésis et ses commandes (discord.py 2.x)."""

from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from nemesis.config import Config, load_config
from nemesis.riot import ApiError, RiotClient, RiotIdError

logger = logging.getLogger("nemesis")


def _explain_api_error(error: ApiError) -> str:
    """Traduit un code HTTP de l'API Riot en message clair en français."""
    code = error.response.status_code
    if code == 404:
        return "Joueur introuvable. Vérifiez le Riot ID (Pseudo#TAG)."
    if code == 403:
        return (
            "Clé API Riot refusée (403). En développement, la clé expire "
            "toutes les 24 h : régénérez-la sur developer.riotgames.com."
        )
    if code == 429:
        return "Trop de requêtes (429, rate limit). Réessayez dans un instant."
    return f"Erreur de l'API Riot (code {code})."


def create_bot(config: Config) -> commands.Bot:
    """Construit le bot, ses intents et enregistre les commandes."""
    # Intents : le contenu des messages est requis pour lire les commandes texte.
    # NB : activer aussi l'intent « Message Content » dans le portail développeur
    # Discord (https://discord.com/developers) sinon les commandes resteront muettes.
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)
    riot = RiotClient(config.riot_api_key, platform=config.default_platform)

    @bot.event
    async def on_ready() -> None:
        logger.info("Connecté en tant que %s (id=%s)", bot.user, bot.user.id if bot.user else "?")

    @bot.command(name="stats")
    async def stats(ctx: commands.Context, *, riot_id: str) -> None:
        """Affiche les statistiques d'un joueur : !stats Pseudo#TAG."""
        # « en train d'écrire » pendant les appels réseau à l'API Riot.
        async with ctx.typing():
            try:
                summary = riot.get_player_summary(riot_id)
            except RiotIdError as exc:
                await ctx.reply(str(exc))
                return
            except ApiError as exc:
                await ctx.reply(_explain_api_error(exc))
                return

        embed = discord.Embed(
            title=f"{summary.game_name}#{summary.tag_line}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Niveau", value=str(summary.level), inline=True)
        embed.add_field(name="Rang", value=summary.rank, inline=True)
        embed.add_field(name="Winrate", value=summary.winrate, inline=True)
        recent = "\n".join(summary.recent) if summary.recent else "Aucune partie récente."
        embed.add_field(name="Dernières parties", value=recent, inline=False)

        await ctx.reply(embed=embed)

    return bot


def main() -> None:
    """Charge la configuration et lance le bot."""
    # Console Windows parfois en cp1252/cp850 : on force l'UTF-8 pour les accents des logs.
    # logging écrit sur stderr par défaut, d'où la reconfiguration des deux flux.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    bot = create_bot(config)
    bot.run(config.discord_token)
