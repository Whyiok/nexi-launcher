"""Application entry point: logging, window creation and the pywebview loop."""

import os
import sys
import threading
from pathlib import Path

from . import config
from .api import LauncherApi
from .logging_setup import log, setup_logging
from .protocol import (LinkServer, forward_link, link_uri_from_args,
                       register_protocol)


def webui_path() -> Path:
    """Locate ``webui/index.html`` next to the exe or in the project root."""
    if getattr(sys, "_MEIPASS", None):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "webui" / "index.html"


def main():
    # The downloaded build starts with --nexi-finish-update to swap files
    # after this process exits; it must not open a window or touch settings.
    from .update import finish_update
    if finish_update(sys.argv[1:]):
        return

    # One-time moves of old data must run before the API opens the folders.
    config.migrate_legacy_files()
    config.migrate_legacy_instances()

    setup_logging()
    log.info("main: starting")
    # The site opens nexi://link?token=... when an account is linked; keep the
    # handler pointing at this exe (it may have moved after an update).
    register_protocol()
    try:
        import webview
    except Exception:
        log.exception("main: could not import webview")
        raise

    api = LauncherApi()
    link_uri = link_uri_from_args(sys.argv[1:])
    page = webui_path()
    log.info("main: webui=%s exists=%s", page, page.is_file())
    window = webview.create_window(
        "Nexi Launcher", str(page), js_api=api,
        width=1180, height=780, min_size=(1000, 690),
        background_color="#030405",
        # The page draws its own title bar (logo, minimize, close); the
        # native frame would show a second one above it. easy_drag stays off so
        # only the .pywebview-drag-region strips move the window.
        frameless=True, easy_drag=False,
    )
    window.events.closing += api.on_close

    def open_link(uri, activate):
        # Called from the link server thread (or at startup with the URL
        # Windows passed to this very process).
        if activate:
            try:
                api.window_activate()
            except Exception:
                log.exception("main: could not activate the window")
        if uri:
            threading.Thread(target=api.nexi_handle_link, args=(uri,),
                             name="nexi-link", daemon=True).start()

    server = LinkServer(lambda uri: open_link(uri, True))
    if not server.start():
        # Another launcher is already running — hand it the link and leave.
        if forward_link(link_uri):
            log.info("main: nexi link forwarded to the running launcher")
            return
        log.warning("main: link port is busy but nobody answered")
    if link_uri:
        open_link(link_uri, False)

    def start_bypass():
        # Runs in its own thread: the UAC prompt must not block the window.
        try:
            api.zapret_autostart()
        except Exception:
            log.exception("main: zapret autostart failed")

    def on_loaded():
        log.info("main: page loaded, bridge ready")
        threading.Thread(target=start_bypass, name="zapret-autostart",
                         daemon=True).start()

    window.events.loaded += on_loaded
    log.info("main: starting webview (gui=edgechromium, debug=%s)",
             bool(os.environ.get("MC_LAUNCHER_DEBUG")))
    webview.start(debug=bool(os.environ.get("MC_LAUNCHER_DEBUG")),
                  gui="edgechromium")
    log.info("main: webview stopped")


if __name__ == "__main__":
    main()
