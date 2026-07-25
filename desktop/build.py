"""Construit l'exécutable Windows de l'app bureau Némésis (icône + fenêtre autonome).

Génère un .ico depuis le logo PNG puis empaquette avec PyInstaller. Le résultat est un
unique `dist/Nemesis-Stats.exe` double-cliquable, à épingler sur le bureau.

    uv run --group desktop python desktop/build.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image

# Console Windows souvent en cp1252 : on force l'UTF-8 pour les symboles des messages.
for _flux in (sys.stdout, sys.stderr):
    if hasattr(_flux, "reconfigure"):
        _flux.reconfigure(encoding="utf-8")

DESKTOP = Path(__file__).resolve().parent
WEB = DESKTOP / "web"
ICON = DESKTOP / "nemesis.ico"
NAME = "Nemesis-Stats"


def generer_icone() -> None:
    """Convertit le logo PNG en .ico multi-tailles pour l'exécutable et la fenêtre."""
    src = WEB / "logo.png"
    img = Image.open(src).convert("RGBA")
    tailles = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ICON, sizes=tailles)
    print(f"Icône générée : {ICON}")


def build() -> None:
    """Lance PyInstaller avec le dossier web embarqué et l'icône Némésis."""
    # `--add-data` : séparateur ';' sous Windows, ':' ailleurs.
    sep = ";" if sys.platform.startswith("win") else ":"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # pas de console derrière la fenêtre
        "--onefile",
        f"--name={NAME}",
        f"--icon={ICON}",
        f"--add-data={WEB}{sep}web",
        str(DESKTOP / "app.py"),
    ]
    print("→", " ".join(cmd))
    subprocess.run(cmd, cwd=DESKTOP, check=True)
    print(f"\n✅ Exécutable prêt : {DESKTOP / 'dist' / (NAME + '.exe')}")
    print("Crée un raccourci sur le bureau vers ce .exe (clic droit → Envoyer vers → Bureau).")


if __name__ == "__main__":
    generer_icone()
    build()
