"""Nexi Launcher entry point.

The backend lives in the :mod:`nexi` package; this file only starts the app so
the build (PyInstaller) and ``python launcher.py`` keep working as before.
"""

from nexi.app import main

if __name__ == "__main__":
    main()
