"""Persisted user configuration.

A single JSON document at ``~/.audix/config.json``. The dataclass is the source of
truth for defaults; unknown keys in an on-disk file are ignored, missing keys fall
back to defaults, so upgrades never crash on an old config.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict

from audix.utils import paths

log = logging.getLogger("audix.config")


@dataclass
class AppConfig:
    # --- output ---------------------------------------------------------------
    output_dir: str = field(default_factory=lambda: str(paths.default_output_dir()))
    audio_format: str = "mp3"          # key from core.formats.FORMATS
    bitrate: str = "320"              # "128" | "192" | "256" | "320" | "native"

    # --- pipeline ------------------------------------------------------------
    concurrent_downloads: int = 3             # 1..16; the top value is "all at once"
    embed_metadata: bool = True
    embed_thumbnail: bool = True
    write_track_numbers: bool = True
    keep_source_file: bool = False
    filename_template: str = "{title}"        # {index}, {title}, {artist}, {album}

    # --- network / stealth -------------------------------------------------
    use_browser_cookies: bool = True
    rotate_user_agent: bool = True
    fixed_user_agent: str = ""               # non-empty overrides rotation
    proxy: str = ""                          # e.g. socks5://127.0.0.1:1080

    # --- editor & profile ----------------------------------------------------
    profile: str = "collector"               # key from core.profiles.PROFILES
    loudness_target: float = -14.0           # LUFS, EBU R128
    normalize_by_default: bool = False
    chapter_split_by_default: bool = True
    silence_threshold_db: float = -50.0
    default_fade_seconds: float = 1.5
    #: Remembered so the editor reopens where the user left off.
    last_edited_file: str = ""

    # --- misc --------------------------------------------------------------
    ffmpeg_dir: str = ""                     # empty => auto-managed
    theme: str = "dark"
    #: Offer a YouTube link found on the clipboard when audix comes to the front.
    watch_clipboard: bool = True

    # ------------------------------------------------------------------------
    @classmethod
    def load(cls) -> "AppConfig":
        path = paths.config_file()
        if not path.exists():
            cfg = cls()
            cfg.save()
            return cfg
        try:
            raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not read config (%s); using defaults", exc)
            return cls()
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in raw.items() if k in known}
        return cls(**clean)

    def save(self) -> None:
        path = paths.config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                json.dumps(asdict(self), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - disk failure
            log.error("Failed to save config: %s", exc)

    # convenience -----------------------------------------------------------
    def update(self, **kwargs: Any) -> None:
        known = {f.name for f in fields(self)}
        for key, value in kwargs.items():
            if key in known:
                setattr(self, key, value)
        self.save()
