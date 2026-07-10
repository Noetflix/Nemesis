---
name: add-riot-endpoint
description: Utiliser pour ajouter un appel à l'API Riot dans riot.py (ex. « récupère la maîtrise des champions », « ajoute les stats de champion »). Guide pour respecter le double routing et renvoyer des dataclasses.
---

# Ajouter un endpoint de l'API Riot

Objectif : ajouter un appel à l'API Riot dans `riot.py` proprement.

## 1. Choisir le bon routing (LE piège n°1)

Chaque endpoint utilise **soit** la plateforme **soit** le cluster régional — jamais au
hasard :

| Endpoint (riotwatcher)                     | Routing à passer            |
| ------------------------------------------ | --------------------------- |
| `riot.account.*` (Account-V1)              | **cluster** `self.region`   |
| `lol.match.*` (Match-V5)                   | **cluster** `self.region`   |
| `lol.summoner.*` (Summoner-V4)             | **plateforme** `self.platform` |
| `lol.league.*` (League-V4)                 | **plateforme** `self.platform` |
| `lol.champion_mastery.*` (Mastery-V4)      | **plateforme** `self.platform` |

`self.region` est déjà déduit de `self.platform` via `PLATFORM_TO_REGION`. Si tu ajoutes une
nouvelle plateforme, complète ce dictionnaire.

## 2. Utiliser le flux moderne uniquement

Toujours partir du **PUUID**. Ne JAMAIS utiliser les endpoints par nom d'invocateur
(`summoner.by_name`), obsolètes.

## 3. Renvoyer une dataclass, pas un dict brut

La couche Discord ne doit jamais manipuler de `dict` d'API. Ajoute/étends une dataclass gelée
(comme `PlayerSummary`) et remplis-la depuis la réponse, avec des accès défensifs
(`.get(...)`) et des conversions de type explicites (`int(...)`).

## 4. Gérer les erreurs API

Laisse remonter `ApiError` (importée depuis `riotwatcher`) jusqu'à `bot.py`, qui la traduit
via `_explain_api_error`. N'attrape `ApiError` dans `riot.py` que si tu peux fournir une
valeur de repli sensée (ex. « Non classé » quand League-V4 ne renvoie rien).

## 5. Vérifier

Lance le skill `check` avant de committer.
