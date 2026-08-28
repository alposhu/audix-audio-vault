"""Construction of the embedded browser's Chromium profile.

Isolated from the browser tab so the profile is created exactly once, owned by the
application (not by a widget that could be destroyed), and so the cookie bridge is
attached before the first page load — a cookie set during the very first request
would otherwise be missed.

Import of the QtWebEngine modules is deferred: on some Linux distributions the
WebEngine package is shipped separately, and audix must still run without it.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from audix.core import user_agents
from audix.core.cookies import CookieBridge
from audix.utils import paths

log = logging.getLogger("audix.ui.web")

_PROFILE = None          # QWebEngineProfile, kept alive for the app's lifetime
_BRIDGE: Optional[CookieBridge] = None


class WebEngineUnavailable(RuntimeError):
    """QtWebEngine could not be imported on this system."""


def webengine_available() -> bool:
    try:
        import PySide6.QtWebEngineCore  # noqa: F401
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return False
    return True


def get_profile(config) -> Tuple[object, CookieBridge]:
    """Return the shared ``(QWebEngineProfile, CookieBridge)`` pair.

    The profile persists cookies to ``~/.audix/webprofile`` so a YouTube sign-in
    survives restarts, and reports the same User-Agent that the yt-dlp backend
    sends — a mismatch between the two is exactly what trips bot detection.
    """
    global _PROFILE, _BRIDGE

    if _PROFILE is not None and _BRIDGE is not None:
        return _PROFILE, _BRIDGE

    try:
        from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
    except ImportError as exc:  # pragma: no cover - platform dependent
        raise WebEngineUnavailable(
            "QtWebEngine is not installed. Install PySide6 with WebEngine support "
            "to use the embedded browser."
        ) from exc

    storage = paths.app_home() / "webprofile"
    storage.mkdir(parents=True, exist_ok=True)
    cache = paths.cache_dir() / "web"
    cache.mkdir(parents=True, exist_ok=True)

    profile = QWebEngineProfile("audix")
    profile.setPersistentStoragePath(str(storage))
    profile.setCachePath(str(cache))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
    profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
    profile.setHttpUserAgent(current_user_agent(config))
    profile.setHttpAcceptLanguage("en-US,en;q=0.9")

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, True)
    settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
    settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, False)
    settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)

    bridge = CookieBridge(profile)

    _PROFILE, _BRIDGE = profile, bridge
    log.info("Web profile ready (storage: %s)", storage)
    return profile, bridge


def current_user_agent(config) -> str:
    return user_agents.session_user_agent(
        fixed=getattr(config, "fixed_user_agent", "") or "",
        rotate=getattr(config, "rotate_user_agent", True),
    )


def apply_user_agent(config) -> str:
    """Push the current session User-Agent onto the live profile. Returns it."""
    agent = current_user_agent(config)
    if _PROFILE is not None:
        _PROFILE.setHttpUserAgent(agent)
    return agent


def rotate_user_agent(config) -> str:
    """Choose a fresh User-Agent and apply it to the profile."""
    user_agents.reset_session()
    return apply_user_agent(config)


def bridge() -> Optional[CookieBridge]:
    """The active cookie bridge, if the browser has been initialised."""
    return _BRIDGE
