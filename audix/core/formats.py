"""Audio format catalogue and the FFmpeg argument builder.

Every user-facing format maps to exactly one :class:`AudioFormat`. The converter
asks this module for the output extension and the encoder argument list; nothing
else in the codebase hard-codes codec knowledge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

NATIVE_BITRATE = "native"
BITRATE_PRESETS: List[str] = ["128", "192", "256", "320", NATIVE_BITRATE]


@dataclass(frozen=True)
class AudioFormat:
    key: str            # stable identifier used in config / UI
    label: str          # human label for the UI
    ext: str            # output file extension (no dot)
    encoder: str        # ffmpeg -c:a value
    lossless: bool
    supports_bitrate: bool
    extra_args: tuple = ()   # extra ffmpeg output args (e.g. container flags)

    def output_args(self, bitrate: str) -> List[str]:
        """FFmpeg output-side arguments for this format at ``bitrate``.

        ``bitrate`` is one of :data:`BITRATE_PRESETS`. For lossless formats and for
        ``native`` it is ignored (VBR / passthrough quality).
        """
        args: List[str] = ["-vn", "-c:a", self.encoder]
        if self.supports_bitrate and bitrate and bitrate != NATIVE_BITRATE:
            args += ["-b:a", f"{bitrate}k"]
        args += list(self.extra_args)
        return args


FORMATS: Dict[str, AudioFormat] = {
    # ---- lossy ----------------------------------------------------------------
    "mp3":  AudioFormat("mp3",  "MP3",              "mp3",  "libmp3lame", False, True,
                        extra_args=("-id3v2_version", "3")),
    "aac":  AudioFormat("aac",  "AAC (ADTS)",       "aac",  "aac",       False, True),
    "m4a":  AudioFormat("m4a",  "M4A (AAC)",        "m4a",  "aac",       False, True,
                        extra_args=("-movflags", "+faststart")),
    "opus": AudioFormat("opus", "Opus",             "opus", "libopus",   False, True),
    "ogg":  AudioFormat("ogg",  "OGG (Vorbis)",     "ogg",  "libvorbis", False, True),
    "wma":  AudioFormat("wma",  "WMA",              "wma",  "wmav2",     False, True),
    # ---- lossless -----------------------------------------------------------
    "flac": AudioFormat("flac", "FLAC",             "flac", "flac",      True,  False,
                        extra_args=("-compression_level", "8")),
    "wav":  AudioFormat("wav",  "WAV (PCM 16-bit)", "wav",  "pcm_s16le", True,  False),
    "alac": AudioFormat("alac", "ALAC (Apple Lossless)", "m4a", "alac",  True,  False,
                        extra_args=("-movflags", "+faststart")),
    "aiff": AudioFormat("aiff", "AIFF (PCM 16-bit)", "aiff", "pcm_s16be", True, False),
}

LOSSY_KEYS = [k for k, v in FORMATS.items() if not v.lossless]
LOSSLESS_KEYS = [k for k, v in FORMATS.items() if v.lossless]


def get(key: str) -> AudioFormat:
    try:
        return FORMATS[key]
    except KeyError:
        raise ValueError(f"Unknown audio format: {key!r}") from None


def is_valid(key: str) -> bool:
    return key in FORMATS
