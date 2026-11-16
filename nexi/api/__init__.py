"""pywebview bridge mixins composed into :class:`LauncherApi`."""

from .base import BaseApi
from .profiles import ProfilesApi
from .accounts import AccountsApi
from .create import CreateApi
from .mods import ModsApi
from .content import ContentApi
from .loaders import LoadersApi
from .skins import SkinsApi
from .diagnostics import DiagnosticsApi
from .home import HomeApi
from .background import BackgroundApi
from .launch import LaunchApi
from .window import WindowApi


class LauncherApi(
    BaseApi,
    ProfilesApi,
    AccountsApi,
    CreateApi,
    ModsApi,
    ContentApi,
    LoadersApi,
    SkinsApi,
    DiagnosticsApi,
    HomeApi,
    BackgroundApi,
    LaunchApi,
    WindowApi,
):
    """State and commands exposed to the page as ``window.pywebview.api``."""
