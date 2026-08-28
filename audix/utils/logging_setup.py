"""Rotating file + console logging, configured once at startup.

Both handlers are forced to UTF-8. Video titles routinely contain emoji, and the
default Windows console encoding (cp1252) raises ``UnicodeEncodeError`` on them —
which logging reports as a noisy "--- Logging error ---" block for every affected
track. Encoding explicitly, with replacement as a backstop, keeps that quiet.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

from audix.utils import paths

_CONFIGURED = False


def _utf8_stream(stream):
    """Return ``stream`` reconfigured for UTF-8 output where that is possible."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    return stream


class _SafeStreamHandler(logging.StreamHandler):
    """Console handler that degrades unencodable characters instead of erroring."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # Last resort for consoles that refuse UTF-8 entirely.
            try:
                message = self.format(record)
                safe = message.encode("ascii", "replace").decode("ascii")
                self.stream.write(safe + self.terminator)
                self.flush()
            except Exception:  # noqa: BLE001 - never let logging break the app
                self.handleError(record)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Initialise the ``audix`` logger tree. Idempotent."""
    global _CONFIGURED
    logger = logging.getLogger("audix")
    if _CONFIGURED:
        return logger

    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        paths.log_file(),
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
        errors="replace",
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # A GUI launched without a console (pythonw.exe) has no usable stderr.
    stream: Optional[object] = sys.stderr
    if stream is not None:
        console = _SafeStreamHandler(_utf8_stream(stream))
        console.setFormatter(fmt)
        logger.addHandler(console)

    logger.propagate = False
    _CONFIGURED = True
    logger.info("Logging initialised -> %s", paths.log_file())
    return logger
