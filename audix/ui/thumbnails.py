"""Video artwork for list rows, fetched without ever blocking a paint.

A row asks for its artwork on every paint and gets ``None`` until it has arrived,
when :attr:`Thumbnails.ready` tells the list to repaint. Asking only from paint
means a 500-track playlist fetches what is on screen, not 500 images, and newest
requests go first so fast scrolling does not queue behind what already scrolled away.
"""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Set

from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from audix.utils import paths

log = logging.getLogger("audix.ui.thumbnails")

#: Wide enough for the inspector at 2x. Row thumbnails downscale from this.
STORED_WIDTH = 480
MAX_IN_MEMORY = 400
MAX_REQUESTS = 6


class Thumbnails(QObject):
    """A memory and disk cache in front of an asynchronous fetch."""

    ready = Signal(str)             # url

    def __init__(self, parent: QObject = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._memory: "OrderedDict[str, QPixmap]" = OrderedDict()
        self._waiting: List[str] = []
        self._in_flight: Set[str] = set()
        self._failed: Set[str] = set()
        self._folder = paths.thumbnails_dir()

    def get(self, url: str) -> Optional[QPixmap]:
        """The artwork at ``url``, or ``None`` with a fetch started."""
        if not url:
            return None
        cached = self._memory.get(url)
        if cached is not None:
            self._memory.move_to_end(url)
            return cached
        if url in self._failed or url in self._in_flight:
            return None

        stored = self._path_for(url)
        if stored.is_file():
            pixmap = QPixmap(str(stored))
            if not pixmap.isNull():
                self._remember(url, pixmap)
                return pixmap

        if url in self._waiting:
            self._waiting.remove(url)
        self._waiting.append(url)
        self._pump()
        return None

    # --------------------------------------------------------------- internals
    def _pump(self) -> None:
        while self._waiting and len(self._in_flight) < MAX_REQUESTS:
            url = self._waiting.pop()       # newest first: that row is on screen
            self._in_flight.add(url)
            request = QNetworkRequest(QUrl(url))
            request.setAttribute(QNetworkRequest.RedirectPolicyAttribute,
                                 QNetworkRequest.NoLessSafeRedirectPolicy)
            reply = self._network.get(request)
            reply.finished.connect(lambda r=reply, u=url: self._on_finished(r, u))

    def _on_finished(self, reply: QNetworkReply, url: str) -> None:
        self._in_flight.discard(url)
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NoError:
            pixmap.loadFromData(bytes(reply.readAll()))
        reply.deleteLater()

        if pixmap.isNull():
            self._failed.add(url)
        else:
            if pixmap.width() > STORED_WIDTH:
                pixmap = pixmap.scaledToWidth(STORED_WIDTH, Qt.SmoothTransformation)
            self._store(url, pixmap)
            self._remember(url, pixmap)
            self.ready.emit(url)
        self._pump()

    def _remember(self, url: str, pixmap: QPixmap) -> None:
        self._memory[url] = pixmap
        while len(self._memory) > MAX_IN_MEMORY:
            self._memory.popitem(last=False)

    def _store(self, url: str, pixmap: QPixmap) -> None:
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            pixmap.save(str(self._path_for(url)), "JPG", 85)
        except OSError as exc:
            log.debug("Could not cache artwork: %s", exc)

    def _path_for(self, url: str) -> Path:
        return self._folder / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.jpg"
