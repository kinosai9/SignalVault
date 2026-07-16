"""SignalVault — 多源投资研究助手."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _get_pkg_version

try:
    __version__ = _get_pkg_version("signalvault")
except PackageNotFoundError:
    __version__ = "0.1.0.dev0"
