"""Linglong Scout — information collection agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("linglong-scout")
except PackageNotFoundError:
    __version__ = "0.0.0"
