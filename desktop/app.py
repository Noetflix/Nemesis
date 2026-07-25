"""Application bureau Némésis : une fenêtre affichant le tableau de bord des stats.

Charge l'interface web locale (``web/index.html``) dans une fenêtre native (PyWebView)
et lui indique quelle API interroger. Par défaut l'API locale du bot ; pour pointer un
VPS plus tard, définir ``NEMESIS_STATS_URL`` (ex. https://mon-vps.exemple/).

Lancement en dev :  uv run --group desktop python desktop/app.py
Build .exe :        uv run --group desktop python desktop/build.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

# URL de l'API de stats. Local par défaut ; surchargée par la variable d'environnement
# pour viser un VPS sans recompiler l'application.
DEFAULT_API = "http://127.0.0.1:8787"


class Bridge:
    """Pont Python↔JS : transmet la config à la page (le schéma file:// interdit ?query)."""

    def __init__(self, api_url: str) -> None:
        self._api_url = api_url

    def config(self) -> dict[str, str]:
        return {"api": self._api_url}


def _web_dir() -> Path:
    """Dossier des fichiers web, qu'on tourne depuis les sources ou un .exe PyInstaller."""
    if getattr(sys, "frozen", False):  # exécutable PyInstaller
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent / "web"


def main() -> None:
    api = os.getenv("NEMESIS_STATS_URL", DEFAULT_API).rstrip("/")
    index = _web_dir() / "index.html"

    webview.create_window(
        "Némésis — Stats",
        url=index.as_uri(),  # file:// sans query : chargé de façon fiable
        js_api=Bridge(api),  # l'URL de l'API arrive via window.pywebview.api.config()
        width=1120,
        height=780,
        min_size=(900, 640),
        background_color="#0d1017",
    )
    webview.start()


if __name__ == "__main__":
    main()
