"""Tab 1 — Embedded Search Browser.

A real Chromium view pointed at YouTube, sharing its User-Agent and cookie jar with
the yt-dlp backend. Browse or search normally; when you are on a video, send it
straight to Quick Convert or queue it with your current defaults.

Signing in here is what unlocks age-restricted and members-only downloads: the
session cookies are exported to ``~/.audix/cookies.txt`` and handed to yt-dlp.

If QtWebEngine is unavailable on the host, the tab degrades to an explanatory
placeholder rather than preventing the application from starting.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from audix.core.downloader import extract_video_id, is_youtube_url
from audix.ui import web_profile
from audix.utils import humanize

log = logging.getLogger("audix.ui.browser")

HOME_URL = "https://www.youtube.com/"
SEARCH_URL = "https://www.youtube.com/results?search_query={}"


class BrowserTab(QWidget):
    """Embedded YouTube browser with hand-off to the conversion pipeline."""

    send_to_convert = Signal(str)          # URL to load into Quick Convert
    queue_requested = Signal(str)          # URL to queue with current defaults
    status_message = Signal(str)           # transient message for the status bar

    def __init__(self, config, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.config = config
        self.view = None
        self._bridge = None
        self._current_url = ""
        self._page_title = ""
        self._cookie_timer: Optional[QTimer] = None

        if web_profile.webengine_available():
            self._build_browser_ui()
        else:
            self._build_unavailable_ui()

    # ------------------------------------------------------------- unavailable
    def _build_unavailable_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("Embedded browser unavailable")
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QLabel(
            "QtWebEngine is not installed on this system, so the in-app browser "
            "cannot be shown.\n\n"
            "Everything else still works — paste links into the Quick Convert tab.\n\n"
            "To enable it, try:  pip install --upgrade PySide6"
        )
        body.setProperty("role", "subtitle")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        layout.addWidget(body)

    # ------------------------------------------------------------------ layout
    def _build_browser_ui(self) -> None:
        from PySide6.QtWebEngineWidgets import QWebEngineView

        profile, self._bridge = web_profile.get_profile(self.config)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        # --- the browser (created first so nav buttons can bind to it) -----
        self.view = QWebEngineView(self)
        self.view.setPage(_build_page(profile, self.view))
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # --- navigation bar ------------------------------------------------
        nav = QHBoxLayout()
        nav.setSpacing(4)

        self.back_button = self._nav_button("←", "Back", self.view.back)
        self.forward_button = self._nav_button("→", "Forward", self.view.forward)
        self.reload_button = self._nav_button("⟳", "Reload", self.view.reload)
        self.home_button = self._nav_button("⌂", "YouTube home", self.go_home)
        self.back_button.setEnabled(False)
        self.forward_button.setEnabled(False)
        for button in (self.back_button, self.forward_button,
                       self.reload_button, self.home_button):
            nav.addWidget(button)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText(
            "Search YouTube, or paste a video / playlist URL…"
        )
        self.address_bar.setClearButtonEnabled(True)
        self.address_bar.returnPressed.connect(self._navigate_from_address_bar)
        nav.addWidget(self.address_bar, 1)

        self.session_label = QLabel("")
        self.session_label.setToolTip(
            "Cookies captured from this browser session and shared with the "
            "download engine."
        )
        nav.addWidget(self.session_label)
        root.addLayout(nav)

        # --- page load progress -------------------------------------------
        self.load_progress = QProgressBar()
        self.load_progress.setRange(0, 100)
        self.load_progress.setTextVisible(False)
        self.load_progress.setFixedHeight(3)
        self.load_progress.hide()
        root.addWidget(self.load_progress)

        self.view.urlChanged.connect(self._on_url_changed)
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadProgress.connect(self.load_progress.setValue)
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.titleChanged.connect(self._on_title_changed)
        root.addWidget(self.view, 1)

        # --- action bar ----------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(10)

        self.detected_label = QLabel("Browse to a video to enable the buttons.")
        self.detected_label.setProperty("role", "hint")
        self.detected_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        actions.addWidget(self.detected_label, 1)

        self.send_button = QPushButton("Send to Quick Convert")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._send_current)
        actions.addWidget(self.send_button)

        self.queue_button = QPushButton("Download Now")
        self.queue_button.setProperty("variant", "primary")
        self.queue_button.setEnabled(False)
        self.queue_button.setToolTip("Queue this page using your default format")
        self.queue_button.clicked.connect(self._queue_current)
        actions.addWidget(self.queue_button)
        root.addLayout(actions)

        # Refresh the cookie badge periodically; sign-in can happen at any time.
        self._cookie_timer = QTimer(self)
        self._cookie_timer.setInterval(4000)
        self._cookie_timer.timeout.connect(self._refresh_session_label)
        self._cookie_timer.start()
        self._refresh_session_label()

        self.view.setUrl(QUrl(HOME_URL))

    def _nav_button(self, text: str, tooltip: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("variant", "nav")
        button.setToolTip(tooltip)
        button.setFixedWidth(36)
        button.clicked.connect(slot)
        return button

    # ------------------------------------------------------------------ public
    def is_available(self) -> bool:
        return self.view is not None

    def go_home(self) -> None:
        self.navigate(HOME_URL)

    def navigate(self, url: str) -> None:
        if self.view is not None:
            self.view.setUrl(QUrl(url))

    def export_cookies(self) -> Optional[str]:
        """Write the current session cookies for yt-dlp; returns the file path."""
        if self._bridge is None:
            return None
        path = self._bridge.export()
        return str(path) if path else None

    def cookie_count(self) -> int:
        return self._bridge.count() if self._bridge is not None else 0

    def clear_session(self) -> None:
        if self._bridge is not None:
            self._bridge.clear_session()
            self._refresh_session_label()
            self.status_message.emit("Browser session cleared.")

    def apply_user_agent(self) -> str:
        """Re-apply the configured User-Agent and reload the page."""
        agent = web_profile.apply_user_agent(self.config)
        if self.view is not None:
            self.view.reload()
        return agent

    def shutdown(self) -> None:
        """Persist cookies and stop the view before the window closes."""
        if self._cookie_timer is not None:
            self._cookie_timer.stop()
        if self._bridge is not None:
            self._bridge.export()
        if self.view is not None:
            self.view.stop()

    # --------------------------------------------------------------- callbacks
    def _navigate_from_address_bar(self) -> None:
        text = self.address_bar.text().strip()
        if not text:
            return
        if text.startswith(("http://", "https://")):
            target = text
        elif "." in text and " " not in text:
            target = f"https://{text}"
        else:
            # Anything else is treated as a YouTube search query.
            encoded = bytes(QUrl.toPercentEncoding(text)).decode("ascii")
            target = SEARCH_URL.format(encoded)
        self.view.setUrl(QUrl(target))

    @Slot(QUrl)
    def _on_url_changed(self, url: QUrl) -> None:
        self._current_url = url.toString()
        if not self.address_bar.hasFocus():
            self.address_bar.setText(self._current_url)
            self.address_bar.setCursorPosition(0)
        self._update_actions()
        history = self.view.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())

    def _on_load_started(self) -> None:
        self.load_progress.setValue(0)
        self.load_progress.show()

    def _on_load_finished(self, ok: bool) -> None:
        self.load_progress.hide()
        self._refresh_session_label()
        if not ok:
            self.status_message.emit("The page failed to load.")

    def _on_title_changed(self, title: str) -> None:
        self._page_title = title or ""
        self._update_actions()

    def _update_actions(self) -> None:
        url = self._current_url
        is_video = bool(extract_video_id(url))
        is_playlist = "list=" in url and is_youtube_url(url)
        enabled = is_video or is_playlist

        self.send_button.setEnabled(enabled)
        self.queue_button.setEnabled(enabled)

        if is_video and is_playlist:
            self.detected_label.setText(
                "Video in a playlist detected — audix will queue the whole playlist."
            )
        elif is_video:
            title = self._page_title.replace(" - YouTube", "").strip() or "Video"
            self.detected_label.setText(f"Detected: {humanize.elide(title, 70)}")
        elif is_playlist:
            self.detected_label.setText("Playlist detected on this page.")
        else:
            self.detected_label.setText("Browse to a video to enable the buttons.")

    def _send_current(self) -> None:
        if self._current_url:
            self.export_cookies()
            self.send_to_convert.emit(self._current_url)

    def _queue_current(self) -> None:
        if self._current_url:
            self.export_cookies()
            self.queue_requested.emit(self._current_url)

    def _refresh_session_label(self) -> None:
        if self._bridge is None:
            return
        count = self._bridge.count()
        if count:
            self.session_label.setText(f"● session: {count} cookies")
            self.session_label.setStyleSheet("color: #4ade80; font-size: 11px;")
        else:
            self.session_label.setText("○ signed out")
            self.session_label.setStyleSheet("color: #6a6a7a; font-size: 11px;")


def _build_page(profile, parent):
    """Create the customised ``QWebEnginePage``.

    Defined as a function so the QtWebEngine import stays inside the branch that
    already established WebEngine is present.
    """
    from PySide6.QtWebEngineCore import QWebEnginePage

    class AudixPage(QWebEnginePage):
        """Keeps ``target=_blank`` navigations inside the same view."""

        def createWindow(self, _window_type):  # noqa: N802 - Qt override
            return self

        def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
            # YouTube is extremely chatty; keep it out of the application log.
            return

        def certificateError(self, error):  # noqa: N802 - Qt override
            log.warning("Certificate error: %s", error.description())
            return False        # never silently accept a bad certificate

    return AudixPage(profile, parent)
