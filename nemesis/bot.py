"""Bot Discord Némésis et ses commandes (discord.py 2.x)."""

from __future__ import annotations

import datetime
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord
from discord.ext import commands, tasks

from nemesis import gifs, trashtalk
from nemesis.config import Config, load_config
from nemesis.riot import (
    ApiError,
    MatchDetail,
    PlayerRank,
    PlayerSummary,
    RankInfo,
    RecentGame,
    RiotClient,
    RiotIdError,
)

logger = logging.getLogger("nemesis")

# Logo Némésis attaché à chaque embed (assets/ est à la racine, à côté du package).
_LOGO_FILENAME = "nemesis.png"
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / _LOGO_FILENAME
_LOGO_ATTACHMENT = f"attachment://{_LOGO_FILENAME}"

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

# Roster de la team suivi par la commande !classement.
TEAM_ROSTER: list[str] = [
    "OT Noetflix#T1WIN",
    "OT Néons#KCORP",
    "OT BaGeR#BGR",
    "Rat Yote#5234",
    "CAP#7459",
]

# Médailles pour les trois premières places du classement.
_MEDALS: dict[int, str] = {1: "🥇", 2: "🥈", 3: "🥉"}


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


async def _reply_embed(ctx: commands.Context, *embeds: discord.Embed) -> None:
    """Répond avec un ou plusieurs embeds en joignant le logo Némésis s'il est disponible."""
    if _LOGO_PATH.is_file():
        await ctx.reply(embeds=list(embeds), file=discord.File(_LOGO_PATH, filename=_LOGO_FILENAME))
    else:
        await ctx.reply(embeds=list(embeds))


async def _post_embed(channel: discord.abc.Messageable, *embeds: discord.Embed) -> None:
    """Poste un ou plusieurs embeds dans un salon, avec le logo joint."""
    if _LOGO_PATH.is_file():
        await channel.send(
            embeds=list(embeds), file=discord.File(_LOGO_PATH, filename=_LOGO_FILENAME)
        )
    else:
        await channel.send(embeds=list(embeds))


def _parse_heures(spec: str, tz_nom: str) -> list[datetime.time]:
    """Transforme « HH:MM,HH:MM » + fuseau en heures de déclenchement (aware)."""
    try:
        tz = ZoneInfo(tz_nom)
    except ZoneInfoNotFoundError, ValueError:
        logger.warning("Fuseau horaire invalide %r, repli sur UTC.", tz_nom)
        tz = datetime.timezone.utc

    heures: list[datetime.time] = []
    for morceau in spec.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            h, m = (int(x) for x in morceau.split(":"))
            heures.append(datetime.time(hour=h, minute=m, tzinfo=tz))
        except ValueError:
            logger.warning("Heure de classement invalide ignorée : %r", morceau)
    return heures


def _rang_court(rank: RankInfo) -> str:
    """Rang en texte brut (sans emoji), pour décrire le joueur à Claude."""
    if not rank.is_ranked:
        return "Non classé"
    division = f" {rank.division}" if rank.division else ""
    winrate = f", {rank.winrate:.0f}% WR" if rank.winrate is not None else ""
    return f"{rank.tier.capitalize()}{division} ({rank.league_points} LP{winrate})"


def _format_leaderboard_entry(position: int, player: PlayerRank, vanne: str) -> str:
    """Formate une entrée du classement : médaille, rang, winrate et vanne."""
    medal = _MEDALS.get(position, f"`#{position}`")
    rank = player.rank
    if rank.is_ranked:
        emoji = RANK_EMOJIS.get(rank.tier.upper(), "🎖️")
        division = f" {rank.division}" if rank.division else ""
        winrate = f" · ⚔️ {rank.winrate:.0f}%" if rank.winrate is not None else ""
        rank_txt = (
            f"{emoji} **{rank.tier.capitalize()}{division}** · {rank.league_points} LP{winrate}"
        )
    else:
        rank_txt = "🎖️ *Non classé*"
    return f"{medal} **{player.game_name}** `#{player.tag_line}`\n{rank_txt}\n> *{vanne}*"


def _build_leaderboard_embed(
    players: list[PlayerRank], erreurs: list[tuple[str, str]], vannes: list[str]
) -> discord.Embed:
    """Construit l'embed du classement (joueurs triés par rang décroissant)."""
    embed = discord.Embed(title="🏆 Classement Solo/Duo de la team", color=discord.Color.gold())
    embed.set_author(name="Némésis · Classement", icon_url=_LOGO_ATTACHMENT)

    # Miniature = icône du leader, pour couronner le premier visuellement.
    leader = players[0]
    if leader.profile_icon_id:
        embed.set_thumbnail(url=leader.profile_icon_url)

    lignes = [
        _format_leaderboard_entry(position, player, vanne)
        for position, (player, vanne) in enumerate(zip(players, vannes), start=1)
    ]
    embed.description = "\n\n".join(lignes)

    # Joueurs non récupérés (Riot ID introuvable, etc.) listés à part.
    if erreurs:
        introuvables = "\n".join(f"• `{riot_id}`" for riot_id, _ in erreurs)
        embed.add_field(name="👻 Fantômes (introuvables)", value=introuvables, inline=False)

    embed.set_footer(text="Némésis • Classement mis à jour", icon_url=_LOGO_ATTACHMENT)
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _preparer_classement(riot: RiotClient, config: Config) -> discord.Embed:
    """Récupère les rangs, génère les vannes et renvoie l'embed du classement.

    Un joueur introuvable est isolé sans casser le tout ; si aucun n'est récupéré,
    renvoie un embed d'erreur. Partagé par la commande !classement et la planification.
    """
    joueurs: list[PlayerRank] = []
    erreurs: list[tuple[str, str]] = []
    for riot_id in TEAM_ROSTER:
        try:
            joueurs.append(riot.get_rank(riot_id))
        except RiotIdError as exc:
            erreurs.append((riot_id, str(exc)))
        except ApiError as exc:
            erreurs.append((riot_id, _explain_api_error(exc)))

    # Aucun joueur récupéré : on renvoie l'erreur (souvent clé 403 expirée).
    if not joueurs:
        detail = "\n".join(f"• `{riot_id}` — {err}" for riot_id, err in erreurs)
        return _error_embed(f"Impossible de récupérer le classement.\n{detail}")

    # Tri par rang décroissant : le meilleur en tête.
    joueurs.sort(key=lambda player: player.rank.score, reverse=True)

    # Vannes générées par l'IA (ou repli local), une par joueur dans l'ordre.
    lignes = [
        trashtalk.LigneClassement(
            position=position,
            total=len(joueurs),
            nom=joueur.game_name,
            rang=_rang_court(joueur.rank),
            is_ranked=joueur.rank.is_ranked,
        )
        for position, joueur in enumerate(joueurs, start=1)
    ]
    vannes = await trashtalk.generer_vannes(
        lignes,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    return _build_leaderboard_embed(joueurs, erreurs, vannes)


# Couleurs de la notification de fin de partie (vert victoire, rouge défaite).
_COULEUR_VICTOIRE = discord.Color(0x2ECC71)
_COULEUR_DEFAITE = discord.Color(0xE74C3C)


def _format_duree(secondes: int) -> str:
    """Formate une durée en secondes vers « M:SS »."""
    minutes, sec = divmod(max(secondes, 0), 60)
    return f"{minutes}:{sec:02d}"


def _format_nombre(valeur: int) -> str:
    """Entier avec séparateur de milliers à la française (espace)."""
    return f"{valeur:,}".replace(",", " ")


def _variation_lp(avant: RankInfo | None, apres: RankInfo) -> str | None:
    """Décrit le gain/perte de LP entre deux rangs, ou None si incalculable.

    Gère les montées/chutes de division et de palier grâce aux LP cumulés.
    """
    if avant is None or not avant.is_ranked or not apres.is_ranked:
        return None
    delta = apres.ladder_points - avant.ladder_points
    if delta == 0:
        return None
    signe = f"+{delta}" if delta > 0 else str(delta)
    if apres.tier != avant.tier:
        suffixe = " · 🎉 Nouveau palier !" if delta > 0 else " · 💥 Chute de palier"
    elif apres.division != avant.division:
        suffixe = " · ⬆️ Division" if delta > 0 else " · ⬇️ Division"
    else:
        suffixe = ""
    fleche = "📈" if delta > 0 else "📉"
    return f"{fleche} {signe} LP{suffixe}"


def _gif_embed(gif_url: str, win: bool) -> discord.Embed:
    """Embed dédié au GIF, posté à côté des stats.

    Le GIF est isolé dans son propre embed : ainsi sa taille (souvent petite) n'impose pas
    la largeur de l'embed de stats, qui garde sa pleine largeur grâce à ses champs.
    """
    couleur = _COULEUR_VICTOIRE if win else _COULEUR_DEFAITE
    return discord.Embed(color=couleur).set_image(url=gif_url)


def _build_match_embed(
    nom: str,
    detail: MatchDetail,
    rank: RankInfo,
    vanne: str,
    variation_lp: str | None = None,
) -> discord.Embed:
    """Construit l'embed riche de fin de partie : stats détaillées + vanne.

    Mise en page pensée pour Discord : 6 champs `inline` (2 rangées pleines de 3) puis un
    champ Rang pleine largeur ; champion, rôle et exploit vivent dans la description pour
    éviter les rangées bancales. Le GIF est ajouté à part (voir _gif_embed).
    """
    issue = "Victoire" if detail.win else "Défaite"
    couleur = _COULEUR_VICTOIRE if detail.win else _COULEUR_DEFAITE
    icone = "🟢" if detail.win else "🔴"

    # En-tête : champion / rôle / niveau, exploit éventuel, puis la vanne.
    role = f" · {detail.role_name}" if detail.role_name else ""
    lignes_desc = [f"**{detail.champion}**{role} · niveau {detail.champ_level}"]
    if detail.multikill_label:
        lignes_desc.append(f"✨ **{detail.multikill_label} !**")
    lignes_desc.append(f"\n> *{vanne}*")

    embed = discord.Embed(
        title=f"{icone} {issue} — {nom}", description="\n".join(lignes_desc), color=couleur
    )
    embed.set_author(name="Némésis · Fin de partie", icon_url=_LOGO_ATTACHMENT)
    embed.set_thumbnail(url=detail.champion_icon_url)

    # Rangée 1 : combat.
    kp = (
        f" · KP {detail.kill_participation * 100:.0f}%"
        if detail.kill_participation is not None
        else ""
    )
    embed.add_field(
        name="⚔️ KDA",
        value=f"**{detail.kills} / {detail.deaths} / {detail.assists}**\nratio {detail.kda_ratio:.1f}{kp}",
        inline=True,
    )
    embed.add_field(
        name="💥 Dégâts",
        value=f"{_format_nombre(detail.damage_champions)}\nsubis {_format_nombre(detail.damage_taken)}",
        inline=True,
    )
    embed.add_field(
        name="👁️ Vision",
        value=f"{detail.vision_score}\n{detail.wards_placed} balises",
        inline=True,
    )

    # Rangée 2 : économie & tempo.
    embed.add_field(
        name="🌾 Farm", value=f"{detail.cs} CS\n{detail.cs_per_min:.1f}/min", inline=True
    )
    embed.add_field(
        name="💰 Or",
        value=f"{_format_nombre(detail.gold)}\n{detail.gold_per_min:.0f}/min",
        inline=True,
    )
    embed.add_field(
        name="⏱️ Durée",
        value=f"{_format_duree(detail.duration_s)}\n{detail.queue_name}",
        inline=True,
    )

    # Rang actuel (pleine largeur) avec le gain/perte de LP bien en évidence.
    if rank.is_ranked:
        emoji = RANK_EMOJIS.get(rank.tier.upper(), "🎖️")
        division = f" {rank.division}" if rank.division else ""
        rang_txt = f"{emoji} **{rank.tier.capitalize()}{division}** · {rank.league_points} LP"
    else:
        rang_txt = "🎖️ Non classé"
    if variation_lp:
        rang_txt += f"　—　{variation_lp}"
    embed.add_field(name="📊 Rang actuel", value=rang_txt, inline=False)

    embed.set_footer(text="Némésis · Données Riot Games", icon_url=_LOGO_ATTACHMENT)
    embed.timestamp = discord.utils.utcnow()
    return embed


async def _finaliser_notif(
    config: Config,
    riot_id: str,
    detail: MatchDetail,
    rank: RankInfo,
    variation_lp: str | None,
) -> list[discord.Embed]:
    """Génère la vanne et le GIF, puis assemble les embeds de fin de partie.

    Renvoie l'embed de stats, suivi d'un embed GIF distinct s'il y a un GIF.
    """
    nom = detail.game_name or riot_id.split("#", 1)[0]
    perf = trashtalk.PerfPartie(
        nom=nom,
        champion=detail.champion,
        role=detail.role_name,
        queue=detail.queue_name,
        win=detail.win,
        kills=detail.kills,
        deaths=detail.deaths,
        assists=detail.assists,
        kda=detail.kda_ratio,
        cs_per_min=detail.cs_per_min,
        degats=detail.damage_champions,
        vision=detail.vision_score,
        multikill=detail.multikill_label,
    )
    vanne = await trashtalk.generer_vanne_partie(
        perf,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
        model=config.llm_model,
    )
    requete = config.giphy_requete_victoire if detail.win else config.giphy_requete_defaite
    gif_url = await gifs.chercher_gif(config.giphy_api_key, requete, detail.win)

    embeds = [_build_match_embed(nom, detail, rank, vanne, variation_lp)]
    if gif_url:
        embeds.append(_gif_embed(gif_url, detail.win))
    return embeds


async def _preparer_notif_partie(
    riot: RiotClient, config: Config, riot_id: str, puuid: str, match_id: str
) -> list[discord.Embed] | None:
    """Construit les embeds de notification d'une partie à la demande (commande !derniere).

    Renvoie None si la partie n'est pas classée. Le gain/perte de LP n'est pas affiché ici
    (pas de rang « avant partie » de référence hors surveillance automatique).
    """
    detail = riot.match_detail(match_id, puuid)
    if detail is None:  # partie hors classé (solo/flex) ou joueur absent.
        return None
    rank = riot.current_rank_for_queue(puuid, detail.queue_id)
    return await _finaliser_notif(config, riot_id, detail, rank, None)


def create_bot(config: Config) -> commands.Bot:
    """Construit le bot, ses intents et enregistre les commandes."""
    # Intents : le contenu des messages est requis pour lire les commandes texte.
    # NB : activer aussi l'intent « Message Content » dans le portail développeur
    # Discord (https://discord.com/developers) sinon les commandes resteront muettes.
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=config.command_prefix, intents=intents)
    riot = RiotClient(config.riot_api_key, platform=config.default_platform)

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

    @bot.command(name="classement")
    async def classement(ctx: commands.Context) -> None:
        """Affiche le classement Solo/Duo de la team : !classement."""
        # « en train d'écrire » pendant les appels réseau (Riot + IA).
        async with ctx.typing():
            embed = await _preparer_classement(riot, config)
        await _reply_embed(ctx, embed)

    @bot.command(name="derniere")
    async def derniere(ctx: commands.Context, *, riot_id: str) -> None:
        """Affiche la notif de la dernière partie classée d'un joueur : !derniere Pseudo#TAG."""
        async with ctx.typing():
            try:
                puuid = riot.resolve_puuid(riot_id)
                match_id = riot.latest_ranked_match_id(puuid)
            except RiotIdError as exc:
                await _reply_embed(ctx, _error_embed(str(exc)))
                return
            except ApiError as exc:
                await _reply_embed(ctx, _error_embed(_explain_api_error(exc)))
                return

            if match_id is None:
                await _reply_embed(ctx, _error_embed("Aucune partie classée récente trouvée."))
                return
            embeds = await _preparer_notif_partie(riot, config, riot_id, puuid, match_id)

        if embeds is None:
            await _reply_embed(ctx, _error_embed("La dernière partie classée est introuvable."))
            return
        await _reply_embed(ctx, *embeds)

    # Planification : poste le classement dans un salon aux heures configurées.
    heures = _parse_heures(config.classement_heures, config.classement_tz)

    @tasks.loop(time=heures)
    async def classement_planifie() -> None:
        salon = bot.get_channel(config.classement_channel_id)
        if salon is None:
            logger.warning(
                "Salon de classement introuvable (id=%s) : publication ignorée.",
                config.classement_channel_id,
            )
            return
        embed = await _preparer_classement(riot, config)
        await _post_embed(salon, embed)

    @classement_planifie.before_loop
    async def _avant_classement() -> None:
        await bot.wait_until_ready()

    # Surveillance des fins de partie : état par joueur du roster.
    # - puuids : cache Riot ID -> PUUID (résolu une fois).
    # - dernier_match : Riot ID -> ID de la dernière partie classée connue.
    # - rank_avant : « Riot ID:queue » -> rang avant la partie, pour le gain/perte de LP.
    # - amorces : joueurs pour qui une base de référence a été enregistrée (anti-spam
    #   au démarrage : on ne notifie que les parties postérieures à l'amorçage).
    puuids: dict[str, str] = {}
    dernier_match: dict[str, str | None] = {}
    rank_avant: dict[str, RankInfo] = {}
    amorces: set[str] = set()
    match_channel = config.match_channel_effectif

    def _puuid(riot_id: str) -> str | None:
        """PUUID du joueur (depuis le cache ou résolu), None si la résolution échoue."""
        puuid = puuids.get(riot_id)
        if puuid is not None:
            return puuid
        try:
            puuid = riot.resolve_puuid(riot_id)
        except ApiError, RiotIdError:
            logger.warning("PUUID introuvable pour %s : joueur ignoré ce tour.", riot_id)
            return None
        puuids[riot_id] = puuid
        return puuid

    async def _notifier_partie(riot_id: str, puuid: str, match_id: str) -> None:
        """Construit et poste la notification d'une partie, avec le gain/perte de LP."""
        salon = bot.get_channel(match_channel)
        if salon is None:
            logger.warning("Salon de notif introuvable (id=%s) : partie ignorée.", match_channel)
            return
        detail = riot.match_detail(match_id, puuid)
        if detail is None:  # partie hors classé : rien à annoncer.
            return

        # Rang après la partie vs rang mémorisé au tour précédent -> variation de LP.
        rank_apres = riot.current_rank_for_queue(puuid, detail.queue_id)
        cle = f"{riot_id}:{detail.queue_id}"
        variation = _variation_lp(rank_avant.get(cle), rank_apres)
        rank_avant[cle] = rank_apres

        embeds = await _finaliser_notif(config, riot_id, detail, rank_apres, variation)
        await _post_embed(salon, *embeds)
        logger.info("Partie annoncée pour %s (match %s).", riot_id, match_id)

    @tasks.loop(minutes=config.match_poll_minutes)
    async def surveillance_parties() -> None:
        for riot_id in TEAM_ROSTER:
            puuid = _puuid(riot_id)
            if puuid is None:
                continue
            try:
                match_id = riot.latest_ranked_match_id(puuid)
            except ApiError as exc:
                logger.warning("Match-V5 en échec pour %s : %s", riot_id, exc)
                continue

            # Premier passage : on mémorise (match + rangs) sans notifier (anti-spam).
            if riot_id not in amorces:
                dernier_match[riot_id] = match_id
                try:
                    for qid, rang in riot.ranks_all_queues(puuid).items():
                        rank_avant[f"{riot_id}:{qid}"] = rang
                except ApiError as exc:
                    logger.warning("Rangs initiaux indisponibles pour %s : %s", riot_id, exc)
                amorces.add(riot_id)
                continue

            if match_id and match_id != dernier_match.get(riot_id):
                dernier_match[riot_id] = match_id
                try:
                    await _notifier_partie(riot_id, puuid, match_id)
                except ApiError as exc:
                    logger.warning("Notification de partie en échec pour %s : %s", riot_id, exc)

    @surveillance_parties.before_loop
    async def _avant_surveillance() -> None:
        await bot.wait_until_ready()

    @bot.event
    async def on_ready() -> None:
        logger.info("Connecté en tant que %s (id=%s)", bot.user, bot.user.id if bot.user else "?")
        # Démarre la planification une seule fois, si un salon et des heures sont définis.
        if config.classement_channel_id and heures and not classement_planifie.is_running():
            classement_planifie.start()
            logger.info(
                "Classement automatique programmé à %s (%s) dans le salon %s.",
                config.classement_heures,
                config.classement_tz,
                config.classement_channel_id,
            )
        # Démarre la surveillance des fins de partie si un salon est disponible.
        if match_channel and not surveillance_parties.is_running():
            surveillance_parties.start()
            logger.info(
                "Surveillance des parties active (toutes les %s min) dans le salon %s.",
                config.match_poll_minutes,
                match_channel,
            )

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
