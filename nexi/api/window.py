"""Native window controls for the launcher's custom title bar."""

import ctypes
import os

_EDGE_CODES = {
    "left": 10, "right": 11, "top": 12, "topleft": 13,
    "topright": 14, "bottom": 15, "bottomleft": 16, "bottomright": 17,
}
_WM_NCLBUTTONDOWN = 0x00A1
_MAXIMIZED = 2


class WindowApi:
    @staticmethod
    def _app_window():
        """The pywebview window, or None while the bridge is starting."""
        try:
            import webview
        except Exception:
            return None
        windows = getattr(webview, "windows", None) or []
        return windows[0] if windows else None

    def window_minimize(self):
        window = self._app_window()
        if window is None:
            return {"ok": False}
        window.minimize()
        return {"ok": True}

    @staticmethod
    def _is_maximized(window):
        native = getattr(window, "native", None)
        try:
            return bool(native is not None
                        and int(getattr(native, "WindowState", 0)) == _MAXIMIZED)
        except (TypeError, ValueError):
            return False

    def window_state(self):
        """Report the current maximized state (the page syncs its glyph)."""
        window = self._app_window()
        if window is None:
            return {"ok": False, "maximized": False}
        return {"ok": True, "maximized": self._is_maximized(window)}

    def window_toggle_maximize(self):
        window = self._app_window()
        if window is None:
            return {"ok": False, "maximized": False}
        maximized = self._is_maximized(window)
        if maximized:
            window.restore()
        else:
            window.maximize()
        return {"ok": True, "maximized": not maximized}

    def window_activate(self):
        """Bring the window to the front (a second launch or a nexi:// link)."""
        window = self._app_window()
        if window is None:
            return {"ok": False}
        try:
            window.restore()
        except Exception:
            pass
        try:
            window.show()
        except Exception:
            pass
        if os.name == "nt":
            native = getattr(window, "native", None)
            handle = (getattr(native, "Handle", None)
                      if native is not None else None)
            if handle is not None:
                try:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(ctypes.c_void_p(int(handle)), 9)
                    user32.SetForegroundWindow(ctypes.c_void_p(int(handle)))
                except Exception:
                    pass
        return {"ok": True}

    def window_close(self):
        window = self._app_window()
        if window is None:
            return {"ok": False}
        # Closing the form raises pywebview's closing event, so on_close()
        # still saves the settings.
        window.destroy()
        return {"ok": True}

    def window_resize(self, edge):
        """Start a native resize from one of the frameless window's edges."""
        edge = str(edge or "")
        if os.name != "nt" or edge not in _EDGE_CODES:
            return {"ok": False}
        window = self._app_window()
        native = getattr(window, "native", None) if window is not None else None
        handle = getattr(native, "Handle", None) if native is not None else None
        if handle is None:
            return {"ok": False}
        try:
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            # Let Windows run its own resize loop; this call returns once the
            # mouse button is released.
            user32.SendMessageW(ctypes.c_void_p(int(handle)),
                                _WM_NCLBUTTONDOWN, _EDGE_CODES[edge], 0)
        except Exception:
            return {"ok": False}
        return {"ok": True}
