"""A small pool of clean, current desktop User-Agent strings.

Used for both the embedded ``QWebEngineView`` and the ``yt-dlp`` HTTP client so the
two present a consistent identity. One UA is chosen per process launch (stable for
the session) unless the user pins a fixed UA in settings.
"""
from __future__ import annotations

import random
from typing import List, Optional

# Mainstream, non-exotic desktop browsers. Kept deliberately short and current.
USER_AGENTS: List[str] = [
    # Chrome / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Chrome / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox / Linux
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Edge / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

_SESSION_UA: Optional[str] = None


def pick_random() -> str:
    return random.choice(USER_AGENTS)


def session_user_agent(fixed: str = "", rotate: bool = True) -> str:
    """Return the UA for this session.

    * ``fixed`` non-empty  -> always that value.
    * ``rotate`` True       -> one random UA, chosen once and cached.
    * ``rotate`` False      -> the first (Chrome/Windows) UA.
    """
    global _SESSION_UA
    if fixed:
        return fixed
    if not rotate:
        return USER_AGENTS[0]
    if _SESSION_UA is None:
        _SESSION_UA = pick_random()
    return _SESSION_UA


def reset_session() -> None:
    """Force a new random UA to be chosen on the next call."""
    global _SESSION_UA
    _SESSION_UA = None
