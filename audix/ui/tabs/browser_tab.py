"""Browse: YouTube, with audix built into it.

A real Chromium view pointed at YouTube, sharing its User-Agent and cookie jar with
the yt-dlp backend. There are three ways to take something from it:

* The dock under the page always names what is on screen and offers Download and
  Add to Queue for it, in the same place, whatever page you are on.
* Hovering any thumbnail shows Download and Queue right on it, so nothing has to be
  opened first.
* Right-clicking any video link offers the same, plus a clean copy of the link.

The address bar's URL is never handed over as it is. It usually carries ``list=``
from whatever Mix or playlist YouTube is playing from, so everything here goes
through :mod:`audix.core.links` and means exactly the video on screen. The list stays
available as a separate, explicit choice in the dock.

Signing in here is what unlocks age-restricted and members-only downloads: the
session cookies are exported to ``~/.audix/cookies.txt`` and handed to yt-dlp.

If QtWebEngine is unavailable on the host, the tab degrades to an explanatory
placeholder rather than preventing the application from starting.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QProgressBar, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from audix.core import links
from audix.core.downloader import MediaEntry
from audix.core.history import DownloadHistory
from audix.ui import icons, web_bridge, web_profile
from audix.ui.output_prefs import OutputPrefs
from audix.ui.thumbnails import Thumbnails
from audix.ui.tokens import COLORS, SPACE, TYPE
from audix.ui.web_bridge import PageBridge, PageInfo, PageLink
from audix.ui.widgets.controls import IconKey, TextKey, add_clear_key
from audix.ui.widgets.format_selector import FormatSelector
from audix.utils import humanize

log = logging.getLogger("audix.ui.browser")

HOME_URL = "https://www.youtube.com/"
SEARCH_URL = "https://www.youtube.com/results?search_query={}"
SIGN_IN_URL = ("https://accounts.google.com/ServiceLogin?service=youtube"
               "&continue=https%3A%2F%2Fwww.youtube.com%2F")

DOCK_THUMB_WIDTH, DOCK_THUMB_HEIGHT = 96, 54


class BrowserTab(QWidget):
    """Embedded YouTube browser with hand-off to the download flow."""

    download_requested = Signal(object)    # MediaEntry to start now
    queue_requested = Signal(object)       # MediaEntry to add to the Queue
    link_requested = Signal(str)           # URL to read, then add to the Queue
    list_requested = Signal(str)           # URL of a whole playlist or Mix
    toast = Signal(str, str)               # message, tone

    def __init__(self, config, prefs: OutputPrefs, thumbnails: Thumbnails,
                 history: DownloadHistory, parent: QWidget = None) -> None:
        super().__init__(parent)
        self.config = config
        self.prefs = prefs
        self.thumbnails = thumbnails
        self.history = history
        self.view = None
        self._bridge = None
        self._page_bridge: Optional[PageBridge] = None
        self._link = links.parse("")
        self._page_title = ""
        self._info: Optional[PageInfo] = None
        self._cookie_timer: Optional[QTimer] = None
        self._loaded = False

        if web_profile.webengine_available():
            self._build_browser_ui()
        else:
            self._build_unavailable_ui()

    # ------------------------------------------------------------- unavailable
    def _build_unavailable_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(SPACE["sm"])

        title = QLabel("This build has no built-in browser")
        title.setProperty("role", "h1")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        body = QLabel(
            "Everything else still works. Copy a link from any browser and paste it\n"
            "into the Queue. For the built-in browser, use the full download of audix,\n"
            "or run  pip install --upgrade PySide6  on a source install."
        )
        body.setProperty("role", "muted")
        body.setAlignment(Qt.AlignCenter)
        layout.addWidget(body)

    # ------------------------------------------------------------------ layout
    def _build_browser_ui(self) -> None:
        profile, self._bridge = web_profile.get_profile(self.config)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # The view comes first so the toolbar keys can bind to it.
        self.view = _build_view(profile, self)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.link_chosen.connect(self._on_context_action)

        self._page_bridge = PageBridge(self)
        self._page_bridge.page_reported.connect(self._on_page_reported)
        self._page_bridge.download_requested.connect(self._download_link)
        self._page_bridge.queue_requested.connect(self._queue_link)
        self._page_bridge.list_requested.connect(self.list_requested)
        web_bridge.install(self.view.page(), self._page_bridge)

        root.addWidget(self._build_toolbar())

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

        root.addWidget(self._build_dock())

        QShortcut(QKeySequence("Ctrl+D"), self, self._download_current).setContext(
            Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+Shift+D"), self, self._queue_current).setContext(
            Qt.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence("Ctrl+L"), self, self._focus_address).setContext(
            Qt.WidgetWithChildrenShortcut)

        # Refresh the session lamp periodically; sign-in can happen at any time.
        self._cookie_timer = QTimer(self)
        self._cookie_timer.setInterval(4000)
        self._cookie_timer.timeout.connect(self._refresh_session)
        self._cookie_timer.start()
        self._refresh_session()
        self.thumbnails.ready.connect(self._on_thumb_ready)
        self._refresh_dock()

    def _build_toolbar(self) -> QFrame:
        bar = QFrame()
        bar.setProperty("role", "stripTop")
        row = QHBoxLayout(bar)
        row.setContentsMargins(SPACE["md"], 8, SPACE["md"], 8)
        row.setSpacing(SPACE["xs"])

        self.back_button = IconKey("back", "Back", self.view.back)
        self.forward_button = IconKey("forward", "Forward", self.view.forward)
        self.reload_button = IconKey("reload", "Reload", self.view.reload)
        self.home_button = IconKey("home", "YouTube home", self.go_home)
        self.back_button.setEnabled(False)
        self.forward_button.setEnabled(False)
        for button in (self.back_button, self.forward_button,
                       self.reload_button, self.home_button):
            row.addWidget(button)

        self.address_bar = QLineEdit()
        self.address_bar.setPlaceholderText("Search YouTube, or paste a link")
        add_clear_key(self.address_bar)
        self.address_bar.addAction(icons.icon("search", 16, COLORS["faint"]),
                                   QLineEdit.LeadingPosition)
        self.address_bar.returnPressed.connect(self._navigate_from_address_bar)
        row.addSpacing(SPACE["xs"])
        row.addWidget(self.address_bar, 1)
        row.addSpacing(SPACE["sm"])

        self.session_key = QToolButton()
        self.session_key.setProperty("role", "key")
        self.session_key.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.session_key.setIcon(icons.icon("person", 16, COLORS["muted"]))
        self.session_key.clicked.connect(self._on_session_clicked)
        row.addWidget(self.session_key)
        return bar

    def _build_dock(self) -> QFrame:
        dock = QFrame()
        dock.setProperty("role", "strip")
        dock.setMinimumHeight(DOCK_THUMB_HEIGHT + 2 * SPACE["sm"] + 2)
        row = QHBoxLayout(dock)
        row.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        row.setSpacing(SPACE["md"])

        self.dock_thumb = QLabel()
        self.dock_thumb.setFixedSize(DOCK_THUMB_WIDTH, DOCK_THUMB_HEIGHT)
        self.dock_thumb.setStyleSheet(f"background-color: {COLORS['well']};")
        self.dock_thumb.setAlignment(Qt.AlignCenter)
        row.addWidget(self.dock_thumb)

        text = QVBoxLayout()
        text.setSpacing(1)
        self.dock_title = QLabel("")
        self.dock_title.setStyleSheet(f"font-weight: 600; font-size: {TYPE['h2'][0]}px;")
        self.dock_title.setTextFormat(Qt.PlainText)
        self.dock_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.dock_title)
        self.dock_meta = QLabel("")
        self.dock_meta.setProperty("role", "muted")
        self.dock_meta.setTextFormat(Qt.PlainText)
        self.dock_meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.dock_meta)
        self.dock_context = QLabel("")
        self.dock_context.setProperty("role", "hint")
        self.dock_context.setTextFormat(Qt.PlainText)
        self.dock_context.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.dock_context)
        row.addLayout(text, 1)

        self.output_key = QToolButton()
        self.output_key.setProperty("role", "key")
        self.output_key.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.output_key.setPopupMode(QToolButton.InstantPopup)
        self.output_key.setIcon(icons.icon("chevron_down", 14, COLORS["muted"]))
        self.output_key.setToolTip("What audio is saved as, here and in the Queue")
        self.output_key.setMenu(self._build_output_menu())
        row.addWidget(self.output_key)
        self.prefs.changed.connect(self._refresh_output_key)
        self._refresh_output_key()

        self.list_key = TextKey("Add playlist to Queue", self._take_list, icon_name="plus")
        row.addWidget(self.list_key)
        self.queue_key = TextKey("Add to Queue", self._queue_current, icon_name="plus")
        row.addWidget(self.queue_key)
        self.download_key = TextKey("Download audio", self._download_current,
                                    variant="primary", icon_name="download")
        self.download_key.setMinimumWidth(150)
        row.addWidget(self.download_key)
        return dock

    def _build_output_menu(self) -> QMenu:
        menu = QMenu(self)
        selector = FormatSelector()
        selector.set_values(self.prefs.audio_format, self.prefs.bitrate)
        selector.changed.connect(
            lambda: self.prefs.set_format(selector.format_key(), selector.bitrate()))
        self.prefs.changed.connect(lambda: _sync_selector(selector, self.prefs))
        holder = QWidget()
        holder.setProperty("role", "clear")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(SPACE["md"], SPACE["sm"], SPACE["md"], SPACE["sm"])
        layout.addWidget(selector)

        action = QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        return menu

    # ------------------------------------------------------------------ public
    def is_available(self) -> bool:
        return self.view is not None

    def go_home(self) -> None:
        self.navigate(HOME_URL)

    def navigate(self, url: str) -> None:
        if self.view is not None:
            self._loaded = True
            self.view.setUrl(QUrl(url))

    def search(self, query: str) -> None:
        encoded = bytes(QUrl.toPercentEncoding(query)).decode("ascii")
        self.navigate(SEARCH_URL.format(encoded))

    def export_cookies(self) -> Optional[str]:
        """Write the current session cookies for yt-dlp; returns the file path."""
        if self._bridge is None:
            return None
        path = self._bridge.export()
        return str(path) if path else None

    def clear_session(self) -> None:
        if self._bridge is not None:
            self._bridge.clear_session()
            self._refresh_session()
            self.toast.emit("Signed out of the browser.", "info")

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
    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        # Loading on first visit, not at launch: Chromium is the heaviest thing in
        # the app, and someone pasting links may never come here.
        if self.view is not None and not self._loaded:
            self.go_home()

    def _focus_address(self) -> None:
        self.address_bar.setFocus()
        self.address_bar.selectAll()

    def _navigate_from_address_bar(self) -> None:
        text = self.address_bar.text().strip()
        if not text:
            return
        found = links.find_links(text)
        if found:
            self.navigate(found[0])
        elif "." in text and " " not in text:
            self.navigate(f"https://{text}")
        else:
            # Anything else is treated as a YouTube search query.
            self.search(text)
        self.view.setFocus()

    @Slot(QUrl)
    def _on_url_changed(self, url: QUrl) -> None:
        text = url.toString()
        previous = self._link
        self._link = links.parse(text)
        if self._link.video_id != previous.video_id or self._link.list_id != previous.list_id:
            self._info = None       # whatever we knew belonged to the last page
        if not self.address_bar.hasFocus():
            self.address_bar.setText(text)
            self.address_bar.setCursorPosition(0)
        self._refresh_dock()
        history = self.view.history()
        self.back_button.setEnabled(history.canGoBack())
        self.forward_button.setEnabled(history.canGoForward())

    def _on_load_started(self) -> None:
        self.load_progress.setValue(0)
        self.load_progress.show()

    def _on_load_finished(self, ok: bool) -> None:
        self.load_progress.hide()
        self._refresh_session()
        if not ok:
            self.toast.emit("The page failed to load.", "error")

    def _on_title_changed(self, title: str) -> None:
        self._page_title = _strip_title(title)
        self._refresh_dock()

    @Slot(object)
    def _on_page_reported(self, info: PageInfo) -> None:
        link = links.parse(info.url)
        if link.video_id == self._link.video_id and link.list_id == self._link.list_id:
            self._info = info
            self._refresh_dock()

    # ---------------------------------------------------------------------- dock
    def _refresh_dock(self) -> None:
        link = self._link
        video, listed = link.has_video, link.has_list
        self.download_key.setVisible(video)
        self.queue_key.setVisible(video)
        self.output_key.setVisible(video or listed)
        self.list_key.setVisible(listed)
        self.list_key.setProperty("variant", "" if video else "primary")
        self.list_key.style().unpolish(self.list_key)
        self.list_key.style().polish(self.list_key)
        self.list_key.setIcon(icons.icon(
            "plus", 16, COLORS["ink"] if video else COLORS["well"]))
        self.list_key.setText("Add the Mix to Queue" if link.is_mix
                              else "Add playlist to Queue")

        info = self._info
        title = (info.title if info else "") or self._page_title
        if video:
            self._set_dock_text(
                title or "This video",
                self._video_facts(info),
                self._context_note(link, info),
            )
            self._set_dock_thumb(links.thumbnail_url(link.video_id))
        elif listed:
            list_title = (info.list_title if info else "") or title or "This playlist"
            count = info.list_count if info else None
            self._set_dock_text(
                list_title,
                humanize.count(count, "video") if count else "Playlist",
                "Adding it puts every track in your Queue, so you can choose from there.",
            )
            self._set_dock_thumb("")
        else:
            self._set_dock_text(
                "Find something to download",
                "Point at any thumbnail for Download and Queue buttons, "
                "or right-click a video link.",
                "",
            )
            self._set_dock_thumb("")

    def _video_facts(self, info: Optional[PageInfo]) -> str:
        parts = []
        if info and info.channel:
            parts.append(info.channel)
        if info and info.duration:
            parts.append(humanize.format_duration(info.duration))
        return " · ".join(parts) or "Video"

    def _context_note(self, link, info: Optional[PageInfo]) -> str:
        note = ""
        if link.is_mix:
            note = "Playing from a YouTube Mix. audix takes only this video."
        elif link.has_list:
            name = info.list_title if info else ""
            count = info.list_count if info else None
            where = f"“{humanize.elide(name, 50)}”" if name else "a playlist"
            size = f" ({humanize.count(count, 'video')})" if count else ""
            note = f"Part of {where}{size}. audix takes only this video."
        if self.history.has(link.video_id):
            return f"You already downloaded this. {note}".strip()
        return note

    def _set_dock_text(self, title: str, meta: str, context: str) -> None:
        self.dock_title.setText(title)
        self.dock_title.setToolTip(title)
        self.dock_meta.setText(meta)
        self.dock_context.setText(context)
        self.dock_context.setVisible(bool(context))

    def _set_dock_thumb(self, url: str) -> None:
        pixmap = self.thumbnails.get(url) if url else None
        if pixmap is None:
            icon_name = "note" if url else "globe"
            self.dock_thumb.setPixmap(icons.pixmap(icon_name, 24, COLORS["border_hi"]))
        else:
            self.dock_thumb.setPixmap(pixmap.scaled(
                self.dock_thumb.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation))

    def _on_thumb_ready(self, url: str) -> None:
        if url == links.thumbnail_url(self._link.video_id):
            self._set_dock_thumb(url)

    def _refresh_output_key(self) -> None:
        self.output_key.setText(self.prefs.describe())

    # ------------------------------------------------------------------- actions
    def _entry_for_page(self) -> Optional[MediaEntry]:
        link = self._link
        if not link.has_video:
            return None
        info = self._info
        return MediaEntry(
            url=link.video_url,
            video_id=link.video_id,
            title=(info.title if info else "") or self._page_title or "YouTube video",
            uploader=info.channel if info else "",
            duration=info.duration if info else None,
        )

    def _download_current(self) -> None:
        entry = self._entry_for_page()
        if entry is None:
            self.toast.emit("Open a video first, then press Download.", "info")
            return
        self.export_cookies()
        self.download_requested.emit(entry)

    def _queue_current(self) -> None:
        entry = self._entry_for_page()
        if entry is None:
            self.toast.emit("Open a video first, then add it to the Queue.", "info")
            return
        self.export_cookies()
        self.queue_requested.emit(entry)

    def _take_list(self) -> None:
        if self._link.has_list:
            self.export_cookies()
            self.list_requested.emit(self._link.url)

    def _entry_for_link(self, picked: PageLink) -> Optional[MediaEntry]:
        link = links.parse(picked.url)
        if not link.has_video:
            return None
        return MediaEntry(url=link.video_url, video_id=link.video_id,
                          title=picked.title or "YouTube video", uploader=picked.channel,
                          duration=picked.duration)

    @Slot(object)
    def _download_link(self, picked: PageLink) -> None:
        entry = self._entry_for_link(picked)
        if entry is not None:
            self.export_cookies()
            self.download_requested.emit(entry)

    @Slot(object)
    def _queue_link(self, picked: PageLink) -> None:
        entry = self._entry_for_link(picked)
        if entry is None:
            return
        self.export_cookies()
        if picked.title:
            self.queue_requested.emit(entry)
        else:
            # A right-clicked link says nothing about the video, so have it read.
            self.link_requested.emit(entry.url)

    @Slot(str, str)
    def _on_context_action(self, action: str, url: str) -> None:
        picked = PageLink(url=url)
        if action == "download":
            self._download_link(picked)
        elif action == "queue":
            self._queue_link(picked)
        elif action == "copy":
            link = links.parse(url)
            QApplication.clipboard().setText(link.video_url or url)
            self.toast.emit("Copied a link to just this video.", "success")
        elif action == "playlist":
            self.list_requested.emit(url)

    def _on_session_clicked(self) -> None:
        if self._bridge is not None and self._bridge.signed_in():
            self.toast.emit(
                "You are signed in. Sign out from Settings, under Browser.", "info")
        else:
            self.navigate(SIGN_IN_URL)

    def _refresh_session(self) -> None:
        if self._bridge is None:
            return
        signed_in = self._bridge.signed_in()
        self.session_key.setText("Signed in" if signed_in else "Sign in")
        self.session_key.setIcon(icons.icon(
            "person", 16, COLORS["success"] if signed_in else COLORS["muted"]))
        self.session_key.setToolTip(
            "Your YouTube session is shared with downloads, so age-restricted and "
            "members-only videos work."
            if signed_in else
            "Optional. Signing in lets audix fetch age-restricted and members-only "
            "videos your account can see."
        )


def _sync_selector(selector: FormatSelector, prefs: OutputPrefs) -> None:
    selector.blockSignals(True)
    selector.set_values(prefs.audio_format, prefs.bitrate)
    selector.blockSignals(False)


def _strip_title(title: str) -> str:
    text = (title or "").strip()
    if text.startswith("(") and ") " in text[:10]:
        text = text.split(") ", 1)[1]       # the unread-count prefix YouTube adds
    return "" if text in ("YouTube", "") else text.removesuffix(" - YouTube").strip()


def _build_view(profile, parent):
    """Create the customised view and page.

    Defined as a function so the QtWebEngine import stays inside the branch that
    already established WebEngine is present.
    """
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView

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

    class AudixView(QWebEngineView):
        """Adds audix's actions to the right-click menu."""

        link_chosen = Signal(str, str)      # action, url

        def contextMenuEvent(self, event) -> None:  # noqa: N802 - Qt override
            request = self.lastContextMenuRequest()
            url = request.linkUrl().toString() if request is not None else ""
            target = links.parse(url or self.url().toString())
            menu = self.createStandardContextMenu()
            first = menu.actions()[0] if menu.actions() else None

            def add(icon_name: str, text: str, action: str) -> None:
                item = menu.addAction(icons.icon(icon_name, 16), text)
                item.triggered.connect(
                    lambda _checked=False: self.link_chosen.emit(action, target.url))
                if first is not None:
                    menu.removeAction(item)
                    menu.insertAction(first, item)

            if target.has_video:
                add("download", "Download audio", "download")
                add("plus", "Add to Queue", "queue")
                add("copy", "Copy link to just this video", "copy")
            if target.has_list:
                add("plus", "Add the whole Mix to Queue" if target.is_mix
                    else "Add the whole playlist to Queue", "playlist")
            if first is not None and (target.has_video or target.has_list):
                menu.insertSeparator(first)
            menu.setAttribute(Qt.WA_DeleteOnClose, True)
            menu.popup(event.globalPos())

    view = AudixView(parent)
    page = AudixPage(profile, view)
    page.setBackgroundColor(QColor(COLORS["well"]))
    view.setPage(page)
    return view
