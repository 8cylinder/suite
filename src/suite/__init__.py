"""suite - keep track of the git status of all your applications."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("suite-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"
