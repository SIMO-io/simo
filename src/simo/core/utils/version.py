from __future__ import annotations

from importlib import metadata


def get_package_version(package_name: str, default: str = 'dev') -> str:
    """Return installed package version.

    Mirrors the historical behavior of:
    `pkg_resources.get_distribution(package_name).version` with a fallback.
    """

    try:
        return metadata.version(package_name)
    except metadata.PackageNotFoundError:
        return default
    except Exception:
        return default


def get_simo_version(default: str = 'dev') -> str:
    return get_package_version('simo', default=default)

