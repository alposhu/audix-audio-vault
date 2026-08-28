"""User profiles.

audix serves four audiences with genuinely different defaults, so rather than
picking one and being wrong for three, it ships presets. A profile sets output
format, loudness target, and how much of the editor is exposed on first open.

Profiles set defaults; they never remove capability. Choosing "Casual" hides
the editor from the first-run path but every tool stays reachable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    tagline: str
    audio_format: str
    bitrate: str
    loudness_target: float          # LUFS
    normalize_by_default: bool
    chapter_split_by_default: bool
    embed_thumbnail: bool
    #: Show the editor prominently on first run rather than keeping it quiet.
    editor_forward: bool
    filename_template: str

    def describe(self) -> str:
        quality = ("lossless" if self.audio_format in ("flac", "wav", "alac", "aiff")
                   else f"{self.bitrate} kbps")
        return f"{self.audio_format.upper()} · {quality} · {self.loudness_target:.0f} LUFS"


PROFILES: Dict[str, Profile] = {
    "collector": Profile(
        key="collector",
        name="Collector",
        tagline="Albums, mixes and live sets, tagged for a permanent library.",
        audio_format="flac",
        bitrate="native",
        loudness_target=-14.0,
        normalize_by_default=False,       # archivists want the original dynamics
        chapter_split_by_default=True,
        embed_thumbnail=True,
        editor_forward=True,
        filename_template="{index} - {title}",
    ),
    "casual": Profile(
        key="casual",
        name="Casual",
        tagline="A few songs for a phone or the car. Fast, with no decisions.",
        audio_format="mp3",
        bitrate="320",
        loudness_target=-14.0,
        normalize_by_default=True,        # consistent volume across a mixed library
        chapter_split_by_default=False,
        embed_thumbnail=True,
        editor_forward=False,
        filename_template="{title}",
    ),
    "podcaster": Profile(
        key="podcaster",
        name="Podcaster",
        tagline="Clips and reference audio, at speech loudness.",
        audio_format="m4a",
        bitrate="192",
        loudness_target=-16.0,            # Apple / spoken-word convention
        normalize_by_default=True,
        chapter_split_by_default=True,
        embed_thumbnail=False,
        editor_forward=True,
        filename_template="{title}",
    ),
    "dj": Profile(
        key="dj",
        name="DJ / Producer",
        tagline="Lossless sources and samples, with pitch and tempo control.",
        audio_format="wav",
        bitrate="native",
        loudness_target=-14.0,
        normalize_by_default=False,       # never pre-process a mixing source
        chapter_split_by_default=True,
        embed_thumbnail=False,
        editor_forward=True,
        filename_template="{artist} - {title}",
    ),
}

DEFAULT_PROFILE = "collector"


def get(key: str) -> Profile:
    return PROFILES.get(key, PROFILES[DEFAULT_PROFILE])


def keys() -> List[str]:
    return list(PROFILES)


def apply_to_config(profile: Profile, config) -> None:
    """Write a profile's defaults into the live configuration."""
    config.update(
        profile=profile.key,
        audio_format=profile.audio_format,
        bitrate=profile.bitrate,
        embed_thumbnail=profile.embed_thumbnail,
        filename_template=profile.filename_template,
        loudness_target=profile.loudness_target,
        normalize_by_default=profile.normalize_by_default,
        chapter_split_by_default=profile.chapter_split_by_default,
    )


def matches(profile: Profile, config) -> bool:
    """Whether the current config still matches a profile's defaults."""
    return (
        getattr(config, "audio_format", None) == profile.audio_format
        and getattr(config, "bitrate", None) == profile.bitrate
        and getattr(config, "filename_template", None) == profile.filename_template
    )


def detect(config) -> Optional[Profile]:
    """The profile the current settings correspond to, if any."""
    for profile in PROFILES.values():
        if matches(profile, config):
            return profile
    return None
