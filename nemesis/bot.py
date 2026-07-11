"""Bot Discord Némésis et ses commandes (discord.py 2.x)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import discord
from discord.ext import commands

from nemesis.config import Config, load_config
from nemesis.riot import ApiError, PlayerSummary, RecentGame, RiotClient, RiotIdError

logger = logging.getLogger("nemesis")

# Logo Némésis attaché à chaque embed (assets/ est à la racine, à côté du package).
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "logo.png"
_LOGO_ATTACHMENT = "attachment://logo.png"

# Couleur de l'embed selon le palier de rang, pour une lecture immédiate.
RANK_COLORS: dict[str, discord.Color] = {
    "IRON": discord.Color(0x51484A),
    "BRONZE": discord.Color(0x8B5A2B),
    "SILVER": discord.Color(0x9FA9B0),
    "GOLD": discord.Color(0xF0B429),
    "PLATINUM": discord.Color(0x3FB7B0),
    "EMERALD": discord.Color(0x1FA85C),
    "DIAMOND": discord.Color(0x5A7FE0),
    "MASTER": discord.Color(0xB94DD8),
    "GRANDMASTER": discord.Color(0xE0424B),
    "CHALLENGER": discord.Color(0xF4C874),
}

# Emblème emoji par palier de rang.
RANK_EMOJIS: dict[str, str] = {
    "IRON": "⚙️",
    "BRONZE": "🥉",
    "SILVER": "🥈",
    "GOLD": "🥇",
    "PLATINUM": "💠",
    "EMERALD": "🟢",
    "DIAMOND": "💎",
    "MASTER": "🔮",
    "GRANDMASTER": "🔥",
    "CHALLENGER": "👑",
}


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


def _winrate_bar(pct: float, segments: int = 10) -> str:
    """Barre de progression en blocs unicode représentant un pourcentage."""
    filled = round(pct / 100 * segments)
    filled = max(0, min(segments, filled))
    return "🟩" * filled + "⬛" * (segments - filled)


def _form_indicator(games: list[RecentGame]) -> str:
    """Suite de carrés verts/rouges résumant la forme récente (plus récent à gauche)."""
    return " ".join("🟩" if game.win else "🟥" for game in games)


def _format_recent_line(game: RecentGame) -> str:
    """Formate une partie sur deux lignes : issue + KDA, puis file / farm / durée."""
    icon = "🟢" if game.win else "🔴"
    kda = f"{game.kills}/{game.deaths}/{game.assists}"
    minutes = game.duration_s // 60
    return (
        f"{icon} **{game.champion}** · `{kda}` · KDA {game.kda_ratio:.1f}\n"
        f"┈ {game.queue_name} · {game.cs_per_min:.1f} cs/min · {minutes} min"
    )


def _build_stats_embed(summary: PlayerSummary) -> discord.Embed:
    """Construit l'embed riche affiché par la commande !stats."""
    rank = summary.rank
    tier = rank.tier.upper()
    color = RANK_COLORS.get(tier, discord.Color.blurple())

    embed = discord.Embed(title=f"{summary.game_name} #{summary.tag_line}", color=color)
    embed.set_author(name="Némésis · Stats League of Legends", icon_url=_LOGO_ATTACHMENT)
    if summary.profile_icon_id:
        embed.set_thumbnail(url=summary.profile_icon_url)

    # Niveau d'invocateur.
    embed.add_field(name="📊 Niveau", value=f"`{summary.level}`", inline=True)

    # Rang classé solo/duo.
    if rank.is_ranked:
        emoji = RANK_EMOJIS.get(tier, "🎖️")
        division = f" {rank.division}" if rank.division else ""
        rang_txt = f"{emoji} **{rank.tier.capitalize()}{division}**\n`{rank.league_points} LP`"
    else:
        rang_txt = "🎖️ *Non classé*"
    embed.add_field(name="🏆 Rang (Solo/Duo)", value=rang_txt, inline=True)

    # Winrate classé avec barre de progression.
    if rank.winrate is not None:
        wr_txt = (
            f"{_winrate_bar(rank.winrate)}\n**{rank.winrate:.0f}%** · {rank.wins}V / {rank.losses}D"
        )
    else:
        wr_txt = "*Aucune partie classée*"
    embed.add_field(name="⚔️ Winrate classé", value=wr_txt, inline=True)

    # Dernières parties + indicateur de forme.
    if summary.recent:
        pertes = len(summary.recent) - summary.recent_wins
        titre = f"📜 Dernières parties · {summary.recent_wins}V / {pertes}D"
        lignes = "\n".join(_format_recent_line(game) for game in summary.recent)
        value = f"{_form_indicator(summary.recent)}\n\n{lignes}"
    else:
        titre = "📜 Dernières parties"
        value = "*Aucune partie récente.*"
    embed.add_field(name=titre, value=value, inline=False)

    embed.set_footer(text="Némésis • Données Riot Games", icon_url=_LOGO_ATTACHMENT)
    embed.timestamp = discord.utils.utcnow()
    return embed


def _error_embed(message: str) -> discord.Embed:
    """Embed rouge uniforme pour signaler une erreur à l'utilisateur."""
    embed = discord.Embed(title="❌ Oups", description=message, color=discord.Color.red())
    embed.set_footer(text="Némésis")
    return embed


async def _reply_embed(ctx: commands.Context, embed: discord.Embed) -> None:
    """Répond avec un embed en joignant le logo Némésis s'il est disponible."""
    if _LOGO_PATH.is_file():
        await ctx.reply(embed=embed, file=discord.File(_LOGO_PATH, filename="logo.png"))
    else:
        await ctx.reply(embed=embed)


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
                await _reply_embed(ctx, _error_embed(str(exc)))
                return
            except ApiError as exc:
                await _reply_embed(ctx, _error_embed(_explain_api_error(exc)))
                return

        await _reply_embed(ctx, _build_stats_embed(summary))

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
