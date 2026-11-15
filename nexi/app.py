"""Application entry point: logging, window creation and the pywebview loop."""

import os
import sys
from pathlib import Path

from . import config
from .api import LauncherApi
from .logging_setup import log, setup_logging


def webui_path() -> Path:
    """Locate ``webui/index.html`` next to the exe or in the project root."""
    if getattr(sys, "_MEIPASS", None):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "webui" / "index.html"


def main():
    # One-time moves of old data must run before the API opens the folders.
    config.migrate_legacy_files()
    config.migrate_legacy_instances()

    setup_logging()
    log.info("main: starting")
    try:
        import webview
    except Exception:
        log.exception("main: could not import webview")
        raise

    api = LauncherApi()
    page = webui_path()
    log.info("main: webui=%s exists=%s", page, page.is_file())
    window = webview.create_window(
        "Nexi Launcher", str(page), js_api=api,
        width=1180, height=780, min_size=(1000, 690),
        background_color="#0a0a0a",
    )
    window.events.closing += api.on_close

    def on_loaded():
        log.info("main: page loaded, bridge ready")

    window.events.loaded += on_loaded
    log.info("main: starting webview (gui=edgechromium, debug=%s)",
             bool(os.environ.get("MC_LAUNCHER_DEBUG")))
    webview.start(debug=bool(os.environ.get("MC_LAUNCHER_DEBUG")),
                  gui="edgechromium")
    log.info("main: webview stopped")


if __name__ == "__main__":
    main()
