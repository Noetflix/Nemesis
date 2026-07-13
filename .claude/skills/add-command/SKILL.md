---
name: add-command
description: Utiliser pour ajouter une nouvelle commande Discord au bot Némésis (ex. « ajoute une commande !mastery »). Guide pour suivre le pattern de bot.py sans y mettre de logique métier.
---

# Ajouter une commande Discord

Objectif : ajouter une commande texte au bot en respectant l'architecture du projet.

## Règle d'or

La **logique métier / appels API vivent dans `riot.py`** et renvoient une **dataclass**.
`bot.py` ne fait qu'orchestrer Discord. Si la commande a besoin de nouvelles données Riot,
ajoute d'abord la méthode dans `riot.py` (voir le skill `add-riot-endpoint`).

## Étapes

1. **(Si besoin de données)** Ajoute/complète une méthode dans `RiotClient` qui renvoie une
   dataclass (pas un `dict` brut). Réutilise `get_player_summary` comme modèle.

2. **Déclare la commande** dans `create_bot()` de `bot.py`, à côté de `stats`, avec le
   décorateur `@bot.command(name="...")` et une docstring française.

3. **Encadre les appels réseau** par `async with ctx.typing():` et un bloc `try/except` :
   ```python
   async with ctx.typing():
       try:
           resultat = riot.ma_methode(...)
       except RiotIdError as exc:
           await ctx.reply(str(exc))
           return
       except ApiError as exc:
           await ctx.reply(_explain_api_error(exc))
           return
   ```
   Ne réinvente pas la gestion d'erreurs : réutilise `_explain_api_error`.

4. **Réponds avec un `discord.Embed`** (titre + `add_field`), jamais un simple texte pour
   des stats. Modèle : la commande `stats`.

5. **Documente la commande dans l'aide** : ajoute un tuple `(usage, description)` à la liste
   `AIDE_COMMANDES` en haut de `bot.py`. C'est ce catalogue qu'affiche la commande `!help` ;
   toute commande omise y sera invisible pour les utilisateurs. Garde une description courte
   en français, avec l'usage sans le préfixe (ex. `"maitrise Pseudo#TAG"`).

6. **Vérifie** avec le skill `check` avant de committer.

## Points de vigilance

- Type hints systématiques ; `from __future__ import annotations` déjà en tête du module.
- Commentaires/docstrings en français, concis.
- Aucun secret en dur.
