"""Whether the user has asked the system for less motion."""
from __future__ import annotations

import sys

#: SPI_GETCLIENTAREAANIMATION, the "Animation effects" switch in Windows settings.
_SPI_GETCLIENTAREAANIMATION = 0x1042


def reduced() -> bool:
    """True when animation should give way to an immediate change of state."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        enabled = ctypes.c_int(1)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not enabled.value
    except (OSError, AttributeError):
        return False
