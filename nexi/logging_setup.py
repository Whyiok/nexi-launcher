"""Rotating file log, stream redirection and crash hooks."""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR, LOG_FILE


log = logging.getLogger("launcher")


class _LogStream:
    """Send stray prints and tracebacks to the log (windowed exe has no console)."""

    def __init__(self, level):
        self._level = level

    def write(self, text):
        text = str(text).rstrip()
        if text:
            log.log(self._level, "%s", text)

    def flush(self):
        pass

    def isatty(self):
        return False


def setup_logging():
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        logging.getLogger("pywebview").setLevel(logging.DEBUG)
        logging.raiseExceptions = False
    except OSError:
        pass
    sys.stdout = _LogStream(logging.INFO)
    sys.stderr = _LogStream(logging.ERROR)

    def handle_exception(exc_type, exc, tb):
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    sys.excepthook = handle_exception

    def handle_thread_exception(args):
        name = args.thread.name if args.thread else "?"
        log.critical("Uncaught exception in thread %s", name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = handle_thread_exception
    log.info("=== launcher start: python %s, frozen=%s, log=%s ===",
             sys.version.split()[0], bool(getattr(sys, "frozen", False)),
             LOG_FILE)
