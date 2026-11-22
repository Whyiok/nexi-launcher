"""``nexi://`` protocol links and single-instance forwarding.

The site opens ``nexi://link?token=...`` when the user clicks "link account".
Windows starts the launcher with that URL in ``sys.argv``; if a copy is already
running, the second process hands the URL to the first one over a small
loopback socket and exits, so only one window ever exists.
"""

import os
import socket
import sys
import threading
import time
from pathlib import Path

from .logging_setup import log

PROTOCOL = "nexi"
HOST = "127.0.0.1"
PORT = 47821
MAGIC = b"NEXI-LINK "
SCHEMES = ("nexi://", "nexilauncher://")
MAX_URI = 4096


def link_uri_from_args(args):
    """The ``nexi://`` URL passed by the browser, or ""."""
    for arg in args:
        value = str(arg or "").strip().strip('"')
        if value.lower().startswith(SCHEMES):
            return value
    return ""


def register_protocol():
    """Point ``nexi://`` at this executable (only the installed exe)."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    try:
        import winreg
        exe = str(Path(sys.executable).resolve())
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                rf"Software\Classes\{PROTOCOL}", 0,
                                winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ,
                              "URL:Nexi Launcher protocol")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
            with winreg.CreateKeyEx(key, r"shell\open\command", 0,
                                    winreg.KEY_WRITE) as command:
                winreg.SetValueEx(command, "", 0, winreg.REG_SZ,
                                  f'"{exe}" "%1"')
        log.info("nexi:// protocol registered for %s", exe)
    except OSError as exc:
        log.warning("could not register the nexi:// protocol: %s", exc)


class LinkServer:
    """Hand a link from a second launcher process to the running one."""

    def __init__(self, callback):
        self._callback = callback
        self._socket = None

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # On Windows SO_REUSEADDR lets two processes bind the same port,
            # which would defeat the single-instance check; use the exclusive
            # option instead.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                server.setsockopt(socket.SOL_SOCKET,
                                  socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((HOST, PORT))
            server.listen(8)
        except OSError:
            server.close()
            return False
        self._socket = server
        threading.Thread(target=self._serve, name="nexi-links",
                         daemon=True).start()
        return True

    def _serve(self):
        while True:
            try:
                connection, _address = self._socket.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(connection,),
                             daemon=True).start()

    def _handle(self, connection):
        try:
            with connection:
                connection.settimeout(3)
                chunks = []
                size = 0
                while size < MAX_URI:
                    chunk = connection.recv(1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if b"\n" in chunk:
                        break
                raw = b"".join(chunks).strip()
                if not raw.startswith(MAGIC):
                    return
                uri = raw[len(MAGIC):].decode("utf-8", "replace").strip()
                connection.sendall(b"OK")
                if uri:
                    self._callback(uri)
        except OSError:
            pass


def forward_link(uri):
    """Send *uri* to the running launcher; True when it accepted it."""
    payload = MAGIC + str(uri or "").encode("utf-8")
    for _attempt in range(6):
        try:
            with socket.create_connection((HOST, PORT), timeout=1.5) as conn:
                conn.sendall(payload)
                conn.settimeout(1.5)
                reply = conn.recv(8)
                return reply.startswith(b"OK")
        except OSError:
            time.sleep(0.2)
    return False
