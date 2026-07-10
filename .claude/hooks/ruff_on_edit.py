"""Hook PostToolUse : formate et lint un fichier .py après son édition.

Reçoit sur stdin le JSON de l'événement Claude Code, en extrait le chemin du
fichier touché, et lance `ruff format` puis `ruff check --fix` dessus si c'est
un fichier Python. Sort toujours en 0 pour ne jamais bloquer l'édition.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# Racine du projet = deux niveaux au-dessus de ce fichier (.claude/hooks/).
_ROOT = Path(__file__).resolve().parents[2]


def _ruff_cmd() -> list[str]:
    """Renvoie la commande de base pour invoquer ruff, la plus fiable possible."""
    # 1) Exécutable ruff du venv du projet (Windows puis POSIX).
    for candidate in (_ROOT / ".venv" / "Scripts" / "ruff.exe", _ROOT / ".venv" / "bin" / "ruff"):
        if candidate.exists():
            return [str(candidate)]
    # 2) ruff présent sur le PATH.
    found = shutil.which("ruff")
    if found:
        return [found]
    # 3) Dernier recours : via uv.
    return ["uv", "run", "ruff"]


def main() -> int:
    try:
        # lstrip d'un éventuel BOM UTF-8 selon l'encodage de l'appelant.
        payload = json.loads(sys.stdin.read().lstrip("﻿"))
    except json.JSONDecodeError, ValueError:
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path")
    if not file_path or not file_path.endswith(".py"):
        return 0

    base = _ruff_cmd()
    for args in (["format", file_path], ["check", "--fix", file_path]):
        try:
            subprocess.run([*base, *args], check=False, cwd=_ROOT)
        except FileNotFoundError:
            # ruff introuvable : on n'échoue pas l'édition pour autant.
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
