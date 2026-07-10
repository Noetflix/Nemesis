---
name: check
description: Utiliser avant chaque commit sur Némésis pour valider le code. Lance ruff format, ruff check --fix, et vérifie que le projet s'importe sans erreur.
---

# Vérification avant commit

À exécuter avant tout commit. Toutes les commandes passent par uv.

## Étapes

```bash
uv run ruff format .            # 1. Formatage
uv run ruff check --fix .       # 2. Lint + corrections automatiques
uv run python -c "import nemesis.bot"   # 3. Le projet s'importe sans erreur
```

## Critères de réussite

- `ruff format` : plus rien à reformater.
- `ruff check` : « All checks passed! ».
- L'import ne lève aucune exception.

Si l'une des étapes échoue, corrige avant de committer. Ne committe jamais `.env` ni aucune
clé.
