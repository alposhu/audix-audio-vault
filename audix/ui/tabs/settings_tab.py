"""Settings.

Everything here writes through to ``~/.audix/config.json`` as soon as it changes,
so there is no save step to forget. Defaults chosen here apply to newly started
downloads; tracks already running keep the settings they were started with, so
changing a preference mid-run never produces a half-and-half batch.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Tuple

from PySide6.QtCore import QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QMessageBox, QScrollArea, QVBoxLayout, QWidget,
)

from audix.core import user_agents
from audix.core.ffmpeg_manager import FFmpegManager
from audix.ui.desktop import reveal_in_file_manager
from audix.ui.output_prefs import OutputPrefs
from audix.ui.tokens import SPACE
from audix.ui.widgets.controls import ParallelCombo, TextKey
from audix.ui.widgets.format_selector import FormatSelector
from audix.ui.widgets.well import Well
from audix.utils import paths

log = logging.getLogger("audix.ui.settings")

SECTION_LABEL_WIDTH = 210
CONTROLS_MAX_WIDTH = 620

#: Every field on the page starts at this one edge, whichever section it is in.
FIELD_LABEL_WIDTH = 96

#: How long after a change the save happens, so a burst of changes writes once.
SAVE_DELAY_MS = 250


class SettingsTab(QWidget):
    """Editor for the persisted application configuration."""

    settings_saved = Signal()
    session_clear_requested = Signal()
    user_agent_changed = Signal()

    def __init__(self, config, prefs: OutputPrefs, ffmpeg: FFmpegManager,
                 parent: QWidget = None) -> None:
        super().__init__(parent)
        self.config = config
        self.prefs = prefs
        self.ffmpeg = ffmpeg
        self._loading = False

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save_to_config)

        self._build_ui()
        self.load_from_config()
        self.prefs.changed.connect(self.load_from_config)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACE["base"], SPACE["md"], SPACE["base"], SPACE["md"])

        well = Well()
        outer.addWidget(well, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        well.body.addWidget(scroll, 1)

        container = QWidget()
        container.setProperty("role", "wellPage")
        root = QVBoxLayout(container)
        root.setContentsMargins(SPACE["2xl"], SPACE["xl"], SPACE["2xl"], SPACE["xl"])
        root.setSpacing(0)
        scroll.setWidget(container)

        self.feedback_label = QLabel("Changes save themselves.")
        self.feedback_label.setProperty("role", "hint")
        root.addWidget(self.feedback_label)
        root.addSpacing(SPACE["base"])

        for builder in (self._saving_section, self._tagging_section, self._downloads_section,
                        self._network_section, self._about_section):
            root.addWidget(_divider())
            title, hint, body = builder()
            root.addLayout(_section(title, hint, body))
        root.addStretch(1)

    def _saving_section(self) -> Tuple[str, str, QWidget]:
        body = QWidget()
        body.setProperty("role", "clear")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["md"])

        folder_row = QHBoxLayout()
        folder_row.setSpacing(SPACE["sm"])
        self.output_input = QLineEdit()
        self.output_input.editingFinished.connect(self._schedule_save)
        folder_row.addWidget(self.output_input, 1)
        folder_row.addWidget(TextKey("Browse…", self._choose_output_dir))
        folder_row.addWidget(TextKey(
            "Open", lambda: reveal_in_file_manager(self.output_input.text().strip()),
            variant="ghost"))
        layout.addLayout(_field("Folder", folder_row))

        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("{title}")
        self.template_input.setToolTip(
            "Placeholders: {index} {title} {artist} {album} {year} {id}"
        )
        self.template_input.editingFinished.connect(self._schedule_save)
        layout.addLayout(_field("File name", self.template_input))

        hint = QLabel("You can use {index}  {title}  {artist}  {album}  {year}  {id}")
        hint.setProperty("role", "hint")
        hint.setContentsMargins(FIELD_LABEL_WIDTH, 0, 0, 0)
        layout.addWidget(hint)

        self.format_selector = FormatSelector(label_width=FIELD_LABEL_WIDTH)
        self.format_selector.changed.connect(self._schedule_save)
        layout.addWidget(self.format_selector)

        self.keep_source_check = QCheckBox(
            "Also keep the original stream, in a _source subfolder"
        )
        self.keep_source_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.keep_source_check)
        return "Saving", "Where audio lands and what it becomes.", body

    def _tagging_section(self) -> Tuple[str, str, QWidget]:
        body = QWidget()
        body.setProperty("role", "clear")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["xs"])

        self.metadata_check = QCheckBox("Write title, artist, album, and year into each file")
        self.metadata_check.toggled.connect(self._on_metadata_toggled)
        self.metadata_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.metadata_check)

        self.thumbnail_check = QCheckBox("Use the video thumbnail as cover art")
        self.thumbnail_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.thumbnail_check)

        self.track_numbers_check = QCheckBox("Number the tracks of a playlist")
        self.track_numbers_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.track_numbers_check)
        return ("Tags", "Covers are converted to JPEG, because most players cannot show "
                "YouTube's WebP images.", body)

    def _downloads_section(self) -> Tuple[str, str, QWidget]:
        body = QWidget()
        body.setProperty("role", "clear")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        row.addWidget(ParallelCombo(self.prefs))
        row.addStretch(1)
        layout.addLayout(row)

        self.clipboard_check = QCheckBox(
            "Offer YouTube links from the clipboard when audix comes to the front"
        )
        self.clipboard_check.setToolTip(
            "The clipboard is only read on this computer, and only to look for a link."
        )
        self.clipboard_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.clipboard_check)
        return ("Downloads", "Higher speeds up a batch but is more likely to be "
                "rate-limited. 3 or 4 is a good balance.", body)

    def _network_section(self) -> Tuple[str, str, QWidget]:
        body = QWidget()
        body.setProperty("role", "clear")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self.cookies_check = QCheckBox("Share browser sign-in with downloads")
        self.cookies_check.setToolTip(
            "Required for age-restricted and members-only videos. Your session never "
            "leaves this computer."
        )
        self.cookies_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.cookies_check)

        self.rotate_ua_check = QCheckBox("Change the browser identity each time audix starts")
        self.rotate_ua_check.toggled.connect(self._on_rotate_toggled)
        self.rotate_ua_check.toggled.connect(self._schedule_save)
        layout.addWidget(self.rotate_ua_check)

        self.ua_combo = QComboBox()
        self.ua_combo.setEditable(True)
        self.ua_combo.addItem("", "")
        for agent in user_agents.USER_AGENTS:
            self.ua_combo.addItem(_shorten_ua(agent), agent)
        self.ua_combo.activated.connect(lambda _i: self._schedule_save())
        self.ua_combo.lineEdit().editingFinished.connect(self._schedule_save)
        layout.addLayout(_field("Fixed identity", self.ua_combo))

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("socks5://127.0.0.1:1080  (optional)")
        self.proxy_input.editingFinished.connect(self._schedule_save)
        layout.addLayout(_field("Proxy", self.proxy_input))

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(TextKey(
            "Sign out of the browser", self._confirm_clear_session, variant="danger",
            tooltip="Sign out and delete all stored cookies"))
        layout.addLayout(row)
        return "Browser", "How audix identifies itself, and your YouTube session.", body

    def _about_section(self) -> Tuple[str, str, QWidget]:
        body = QWidget()
        body.setProperty("role", "clear")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE["sm"])

        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setWordWrap(True)
        layout.addWidget(self.ffmpeg_label)

        row = QHBoxLayout()
        row.setSpacing(SPACE["sm"])
        row.addWidget(TextKey("Open audix folder",
                              lambda: reveal_in_file_manager(str(paths.app_home()))))
        row.addWidget(TextKey("Open log file",
                              lambda: reveal_in_file_manager(str(paths.log_file()))))
        row.addStretch(1)
        row.addWidget(TextKey("Reset settings", self._reset_defaults, variant="danger",
                              tooltip="Put every setting back to its default"))
        layout.addLayout(row)

        self._refresh_ffmpeg_label()
        return "About", "What audix relies on, and where it keeps things.", body

    # ------------------------------------------------------------------ config
    @Slot()
    def load_from_config(self) -> None:
        self._loading = True
        cfg = self.config
        self.output_input.setText(cfg.output_dir)
        self.output_input.setCursorPosition(0)
        self.template_input.setText(cfg.filename_template)
        self.format_selector.set_values(cfg.audio_format, cfg.bitrate)
        self.keep_source_check.setChecked(cfg.keep_source_file)

        self.metadata_check.setChecked(cfg.embed_metadata)
        self.thumbnail_check.setChecked(cfg.embed_thumbnail)
        self.track_numbers_check.setChecked(cfg.write_track_numbers)
        self._on_metadata_toggled(cfg.embed_metadata)
        self.clipboard_check.setChecked(cfg.watch_clipboard)

        self.cookies_check.setChecked(cfg.use_browser_cookies)
        self.rotate_ua_check.setChecked(cfg.rotate_user_agent)
        index = self.ua_combo.findData(cfg.fixed_user_agent)
        if index >= 0:
            self.ua_combo.setCurrentIndex(index)
        else:
            self.ua_combo.setCurrentText(cfg.fixed_user_agent)
        self._on_rotate_toggled(cfg.rotate_user_agent)
        self.proxy_input.setText(cfg.proxy)
        self._loading = False

    def _schedule_save(self) -> None:
        if not self._loading:
            self._save_timer.start()

    @Slot()
    def save_to_config(self) -> None:
        output_dir = self.output_input.text().strip() or str(paths.default_output_dir())
        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_feedback(f"That folder cannot be used: {exc}", error=True)
            return

        previous_ua = (self.config.fixed_user_agent, self.config.rotate_user_agent)

        self.config.update(
            output_dir=output_dir,
            filename_template=self.template_input.text().strip() or "{title}",
            audio_format=self.format_selector.format_key(),
            bitrate=self.format_selector.bitrate(),
            keep_source_file=self.keep_source_check.isChecked(),
            embed_metadata=self.metadata_check.isChecked(),
            embed_thumbnail=self.thumbnail_check.isChecked(),
            write_track_numbers=self.track_numbers_check.isChecked(),
            watch_clipboard=self.clipboard_check.isChecked(),
            use_browser_cookies=self.cookies_check.isChecked(),
            rotate_user_agent=self.rotate_ua_check.isChecked(),
            fixed_user_agent=self._selected_user_agent(),
            proxy=self.proxy_input.text().strip(),
        )
        self.prefs.refresh()

        self._set_feedback("Saved.", success=True)
        self.settings_saved.emit()
        if previous_ua != (self.config.fixed_user_agent, self.config.rotate_user_agent):
            self.user_agent_changed.emit()

    def _selected_user_agent(self) -> str:
        data = self.ua_combo.currentData()
        if data:
            return str(data)
        text = self.ua_combo.currentText().strip()
        # A shortened label from the dropdown is not a usable UA string.
        return "" if text.endswith("…") else text

    # ----------------------------------------------------------------- actions
    def _choose_output_dir(self) -> None:
        current = self.output_input.text().strip() or str(paths.default_output_dir())
        chosen = QFileDialog.getExistingDirectory(self, "Choose where audio is saved", current)
        if chosen:
            self.output_input.setText(chosen)
            self._schedule_save()

    def _confirm_clear_session(self) -> None:
        answer = QMessageBox.question(
            self,
            "Sign out of the browser?",
            "This signs you out and deletes every stored cookie.\n\n"
            "Age-restricted and members-only downloads will stop working until you "
            "sign in again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.session_clear_requested.emit()
            self._set_feedback("Signed out of the browser.", success=True)

    def _reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset settings?",
            "Put every setting back to its default value?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        from audix.config import AppConfig

        defaults = AppConfig()
        for field_name in vars(defaults):
            setattr(self.config, field_name, getattr(defaults, field_name))
        self.config.save()
        self.prefs.refresh()
        self._set_feedback("Settings are back to their defaults.", success=True)
        self.settings_saved.emit()

    # --------------------------------------------------------------- internals
    def _on_metadata_toggled(self, enabled: bool) -> None:
        self.thumbnail_check.setEnabled(enabled)
        self.track_numbers_check.setEnabled(enabled)

    def _on_rotate_toggled(self, rotating: bool) -> None:
        self.ua_combo.setEnabled(not rotating)
        self.ua_combo.setToolTip(
            "Turn off the changing identity above to pin one here." if rotating else
            "Use one specific identity for both the browser and downloads."
        )

    def _refresh_ffmpeg_label(self) -> None:
        if self.ffmpeg.ready:
            self.ffmpeg_label.setProperty("role", "success")
            self.ffmpeg_label.setText(f"FFmpeg is ready.\n{self.ffmpeg.ffmpeg()}")
        else:
            self.ffmpeg_label.setProperty("role", "error")
            self.ffmpeg_label.setText(
                "FFmpeg is not available, so downloads are blocked. Restart audix to "
                "set it up again."
            )
        self.ffmpeg_label.style().unpolish(self.ffmpeg_label)
        self.ffmpeg_label.style().polish(self.ffmpeg_label)

    def _set_feedback(self, message: str, error: bool = False,
                      success: bool = False) -> None:
        role = "error" if error else ("success" if success else "hint")
        self.feedback_label.setProperty("role", role)
        self.feedback_label.setText(message)
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)


def _field(label: str, control) -> QHBoxLayout:
    """A labelled field on the page's shared edge."""
    row = QHBoxLayout()
    row.setSpacing(0)
    caption = QLabel(label)
    caption.setFixedWidth(FIELD_LABEL_WIDTH)
    row.addWidget(caption)
    if isinstance(control, QLayout):
        row.addLayout(control, 1)
    else:
        row.addWidget(control, 1)
    return row


def _divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFixedHeight(1)
    return line


def _section(title: str, hint: str, body: QWidget) -> QHBoxLayout:
    """One settings row: what this group is on the left, its controls on the right."""
    row = QHBoxLayout()
    row.setContentsMargins(0, SPACE["lg"], 0, SPACE["xl"])
    row.setSpacing(SPACE["2xl"])

    intro = QVBoxLayout()
    intro.setSpacing(SPACE["xs"])
    heading = QLabel(title)
    heading.setProperty("role", "h2")
    heading.setFixedWidth(SECTION_LABEL_WIDTH)
    intro.addWidget(heading)
    note = QLabel(hint)
    note.setProperty("role", "hint")
    note.setWordWrap(True)
    note.setFixedWidth(SECTION_LABEL_WIDTH)
    intro.addWidget(note)
    intro.addStretch(1)
    row.addLayout(intro)

    body.setMaximumWidth(CONTROLS_MAX_WIDTH)
    row.addWidget(body, 1, Qt.AlignTop)
    row.addStretch(0)
    return row


def _shorten_ua(agent: str) -> str:
    """A readable one-line label for a long User-Agent string."""
    for marker in ("Edg/", "Firefox/", "Version/", "Chrome/"):
        if marker in agent:
            browser = marker.rstrip("/")
            platform = "Windows" if "Windows" in agent else (
                "macOS" if "Mac OS" in agent else "Linux"
            )
            return f"{browser} on {platform}"
    return agent[:60] + "…"
