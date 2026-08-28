"""Tab 4 — Settings.

Everything here writes through to ``~/.audix/config.json`` on save. Defaults chosen
in this tab apply to newly queued tasks; tasks already in the queue keep the
settings they were created with, so changing a preference mid-run never produces a
half-and-half batch.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from audix.core import user_agents
from audix.core.ffmpeg_manager import FFmpegManager
from audix.ui.widgets.download_item import reveal_in_file_manager
from audix.ui.widgets.format_selector import FormatSelector
from audix.utils import paths

log = logging.getLogger("audix.ui.settings")


class SettingsTab(QWidget):
    """Editor for the persisted application configuration."""

    settings_saved = Signal()
    session_clear_requested = Signal()
    user_agent_changed = Signal()

    def __init__(self, config, queue, ffmpeg: FFmpegManager,
                 parent: QWidget = None) -> None:
        super().__init__(parent)
        self.config = config
        self.queue = queue
        self.ffmpeg = ffmpeg

        self._build_ui()
        self.load_from_config()

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, 1)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(24, 22, 24, 16)
        root.setSpacing(16)
        scroll.setWidget(container)

        title = QLabel("Settings")
        title.setProperty("role", "title")
        root.addWidget(title)

        root.addWidget(self._output_group())
        root.addWidget(self._metadata_group())
        root.addWidget(self._performance_group())
        root.addWidget(self._network_group())
        root.addWidget(self._dependencies_group())
        root.addStretch(1)

        # --- sticky action bar --------------------------------------------
        actions = QHBoxLayout()
        actions.setContentsMargins(24, 8, 24, 16)
        self.feedback_label = QLabel("")
        self.feedback_label.setProperty("role", "hint")
        actions.addWidget(self.feedback_label, 1)

        reset = QPushButton("Reset to Defaults")
        reset.setProperty("variant", "ghost")
        reset.clicked.connect(self._reset_defaults)
        actions.addWidget(reset)

        save = QPushButton("Save Settings")
        save.setProperty("variant", "primary")
        save.setMinimumWidth(150)
        save.clicked.connect(self.save_to_config)
        actions.addWidget(save)
        outer.addLayout(actions)

    def _output_group(self) -> QGroupBox:
        group = QGroupBox("Output")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.output_input = QLineEdit()
        folder_row.addWidget(self.output_input, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._choose_output_dir)
        folder_row.addWidget(browse)
        open_folder = QPushButton("Open")
        open_folder.setProperty("variant", "ghost")
        open_folder.clicked.connect(
            lambda: reveal_in_file_manager(self.output_input.text().strip())
        )
        folder_row.addWidget(open_folder)
        form.addRow("Default output folder", folder_row)

        self.template_input = QLineEdit()
        self.template_input.setPlaceholderText("{title}")
        self.template_input.setToolTip(
            "Placeholders: {index} {title} {artist} {album} {year} {id}"
        )
        form.addRow("Filename template", self.template_input)
        layout.addLayout(form)

        hint = QLabel(
            "Template placeholders: {index}  {title}  {artist}  {album}  {year}  {id}"
        )
        hint.setProperty("role", "hint")
        layout.addWidget(hint)

        self.format_selector = FormatSelector(compact=False)
        layout.addWidget(self.format_selector)

        self.keep_source_check = QCheckBox(
            "Keep the original downloaded stream in a _source subfolder"
        )
        layout.addWidget(self.keep_source_check)
        return group

    def _metadata_group(self) -> QGroupBox:
        group = QGroupBox("Metadata && tagging")
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        self.metadata_check = QCheckBox(
            "Embed metadata (title, artist, album, year)"
        )
        self.metadata_check.toggled.connect(self._on_metadata_toggled)
        layout.addWidget(self.metadata_check)

        self.thumbnail_check = QCheckBox("Embed the video thumbnail as cover art")
        layout.addWidget(self.thumbnail_check)

        self.track_numbers_check = QCheckBox(
            "Write track numbers for playlist items"
        )
        layout.addWidget(self.track_numbers_check)

        hint = QLabel(
            "Cover art is converted to JPEG before embedding, because most players "
            "cannot display YouTube's WebP thumbnails."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return group

    def _performance_group(self) -> QGroupBox:
        group = QGroupBox("Performance")
        layout = QFormLayout(group)
        layout.setSpacing(10)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 12)
        self.concurrency_spin.setSuffix("  simultaneous downloads")
        self.concurrency_spin.setToolTip(
            "Higher values finish batches faster but are more likely to be "
            "rate-limited. 3–4 is a good balance."
        )
        layout.addRow("Concurrency", self.concurrency_spin)
        return group

    def _network_group(self) -> QGroupBox:
        group = QGroupBox("Browser && network")
        layout = QVBoxLayout(group)
        layout.setSpacing(10)

        self.cookies_check = QCheckBox(
            "Share embedded-browser cookies with the download engine"
        )
        self.cookies_check.setToolTip(
            "Required for age-restricted and members-only content. Cookies never "
            "leave your machine."
        )
        layout.addWidget(self.cookies_check)

        self.rotate_ua_check = QCheckBox(
            "Rotate the User-Agent each time audix starts"
        )
        self.rotate_ua_check.toggled.connect(self._on_rotate_toggled)
        layout.addWidget(self.rotate_ua_check)

        form = QFormLayout()
        form.setSpacing(10)
        self.ua_combo = QComboBox()
        self.ua_combo.setEditable(True)
        self.ua_combo.addItem("", "")
        for agent in user_agents.USER_AGENTS:
            self.ua_combo.addItem(_shorten_ua(agent), agent)
        form.addRow("Pinned User-Agent", self.ua_combo)

        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText("socks5://127.0.0.1:1080  (optional)")
        form.addRow("Proxy", self.proxy_input)
        layout.addLayout(form)

        session_row = QHBoxLayout()
        session_row.addStretch(1)
        clear_session = QPushButton("Clear Browser Session")
        clear_session.setProperty("variant", "danger")
        clear_session.setToolTip("Sign out and delete all stored cookies")
        clear_session.clicked.connect(self._confirm_clear_session)
        session_row.addWidget(clear_session)
        layout.addLayout(session_row)
        return group

    def _dependencies_group(self) -> QGroupBox:
        group = QGroupBox("Dependencies")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self.ffmpeg_label = QLabel("")
        self.ffmpeg_label.setWordWrap(True)
        self.ffmpeg_label.setTextInteractionFlags(
            self.ffmpeg_label.textInteractionFlags()
        )
        layout.addWidget(self.ffmpeg_label)

        row = QHBoxLayout()
        row.addStretch(1)
        open_bin = QPushButton("Open audix Folder")
        open_bin.setProperty("variant", "ghost")
        open_bin.clicked.connect(lambda: reveal_in_file_manager(str(paths.app_home())))
        row.addWidget(open_bin)

        open_log = QPushButton("Open Log File")
        open_log.setProperty("variant", "ghost")
        open_log.clicked.connect(lambda: reveal_in_file_manager(str(paths.log_file())))
        row.addWidget(open_log)
        layout.addLayout(row)

        self._refresh_ffmpeg_label()
        return group

    # ------------------------------------------------------------------ config
    def load_from_config(self) -> None:
        cfg = self.config
        self.output_input.setText(cfg.output_dir)
        self.template_input.setText(cfg.filename_template)
        self.format_selector.set_values(cfg.audio_format, cfg.bitrate)
        self.keep_source_check.setChecked(cfg.keep_source_file)

        self.metadata_check.setChecked(cfg.embed_metadata)
        self.thumbnail_check.setChecked(cfg.embed_thumbnail)
        self.track_numbers_check.setChecked(cfg.write_track_numbers)
        self._on_metadata_toggled(cfg.embed_metadata)

        self.concurrency_spin.setValue(cfg.concurrent_downloads)

        self.cookies_check.setChecked(cfg.use_browser_cookies)
        self.rotate_ua_check.setChecked(cfg.rotate_user_agent)
        index = self.ua_combo.findData(cfg.fixed_user_agent)
        if index >= 0:
            self.ua_combo.setCurrentIndex(index)
        else:
            self.ua_combo.setCurrentText(cfg.fixed_user_agent)
        self._on_rotate_toggled(cfg.rotate_user_agent)
        self.proxy_input.setText(cfg.proxy)

    @Slot()
    def save_to_config(self) -> None:
        output_dir = self.output_input.text().strip() or str(paths.default_output_dir())
        try:
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_feedback(f"Cannot use that output folder: {exc}", error=True)
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
            concurrent_downloads=self.concurrency_spin.value(),
            use_browser_cookies=self.cookies_check.isChecked(),
            rotate_user_agent=self.rotate_ua_check.isChecked(),
            fixed_user_agent=self._selected_user_agent(),
            proxy=self.proxy_input.text().strip(),
        )
        self.queue.set_concurrency(self.config.concurrent_downloads)

        self._set_feedback("Settings saved.", success=True)
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
        chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", current)
        if chosen:
            self.output_input.setText(chosen)

    def _confirm_clear_session(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear browser session?",
            "This signs you out of the embedded browser and deletes every stored "
            "cookie.\n\nAge-restricted and members-only downloads will stop working "
            "until you sign in again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.session_clear_requested.emit()
            self._set_feedback("Browser session cleared.", success=True)

    def _reset_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset settings?",
            "Restore every setting to its default value?",
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
        self.load_from_config()
        self.queue.set_concurrency(self.config.concurrent_downloads)
        self._set_feedback("Settings reset to defaults.", success=True)
        self.settings_saved.emit()

    # --------------------------------------------------------------- internals
    def _on_metadata_toggled(self, enabled: bool) -> None:
        self.thumbnail_check.setEnabled(enabled)
        self.track_numbers_check.setEnabled(enabled)

    def _on_rotate_toggled(self, rotating: bool) -> None:
        self.ua_combo.setEnabled(not rotating)
        self.ua_combo.setToolTip(
            "Disabled while rotation is on — audix picks one automatically."
            if rotating else
            "Pin a specific User-Agent for both the browser and the downloader."
        )

    def _refresh_ffmpeg_label(self) -> None:
        if self.ffmpeg.ready:
            self.ffmpeg_label.setProperty("role", "success")
            self.ffmpeg_label.setText(
                f"FFmpeg is ready.\n{self.ffmpeg.ffmpeg()}"
            )
        else:
            self.ffmpeg_label.setProperty("role", "error")
            self.ffmpeg_label.setText("FFmpeg is not available — downloads are blocked.")
        self.ffmpeg_label.style().unpolish(self.ffmpeg_label)
        self.ffmpeg_label.style().polish(self.ffmpeg_label)

    def _set_feedback(self, message: str, error: bool = False,
                      success: bool = False) -> None:
        role = "error" if error else ("success" if success else "hint")
        self.feedback_label.setProperty("role", role)
        self.feedback_label.setText(message)
        self.feedback_label.style().unpolish(self.feedback_label)
        self.feedback_label.style().polish(self.feedback_label)


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

