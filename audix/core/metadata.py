"""Metadata modelling and tag writing.

:class:`TrackMetadata` is the format-neutral description of a track; :func:`apply_tags`
writes it into whichever container the converter produced. Each container family has
its own writer because ID3, MP4 atoms, Vorbis comments and ASF attributes share no
common API.

Cover art is normalised to JPEG first -- YouTube serves WebP thumbnails, which most
players will not render as album art.
"""
from __future__ import annotations

import base64
import logging
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from audix.utils.proc import no_window_kwargs

log = logging.getLogger("audix.metadata")

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class TrackMetadata:
    """Everything audix knows about one track, independent of output format."""

    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    track_number: Optional[int] = None
    track_total: Optional[int] = None
    comment: str = ""
    source_url: str = ""
    cover: Optional[bytes] = None
    cover_mime: str = "image/jpeg"

    @classmethod
    def from_info(
        cls,
        info: Dict[str, Any],
        playlist_title: str = "",
        track_number: Optional[int] = None,
        track_total: Optional[int] = None,
    ) -> "TrackMetadata":
        """Build metadata from a yt-dlp info dictionary.

        yt-dlp exposes music-specific fields (``track``, ``artist``, ``album``) for
        videos that carry them; those are preferred over the generic title/uploader
        so official music uploads tag correctly.
        """
        artist = (
            info.get("artist")
            or info.get("creator")
            or info.get("uploader")
            or info.get("channel")
            or ""
        )
        title = info.get("track") or info.get("title") or ""
        album = info.get("album") or playlist_title or title

        return cls(
            title=str(title),
            artist=str(artist),
            album=str(album),
            album_artist=str(info.get("album_artist") or artist),
            year=_extract_year(info),
            track_number=track_number,
            track_total=track_total,
            comment=str(info.get("webpage_url") or ""),
            source_url=str(info.get("webpage_url") or ""),
        )


def _extract_year(info: Dict[str, Any]) -> str:
    release_year = info.get("release_year")
    if release_year:
        return str(release_year)
    for key in ("release_date", "upload_date"):
        value = info.get(key)
        if value and len(str(value)) >= 4 and str(value)[:4].isdigit():
            return str(value)[:4]
    return ""


# ---------------------------------------------------------------------------
# Cover art
# ---------------------------------------------------------------------------

def best_thumbnail_url(info: Dict[str, Any]) -> str:
    """Pick the highest-resolution thumbnail, preferring JPEG over WebP."""
    thumbnails: List[Dict[str, Any]] = info.get("thumbnails") or []
    if not thumbnails:
        return str(info.get("thumbnail") or "")

    def score(thumb: Dict[str, Any]) -> tuple:
        url = str(thumb.get("url") or "")
        width = thumb.get("width") or 0
        height = thumb.get("height") or 0
        is_jpeg = 1 if (".jpg" in url or ".jpeg" in url) else 0
        return (is_jpeg, width * height, thumb.get("preference") or 0)

    best = max(thumbnails, key=score)
    return str(best.get("url") or info.get("thumbnail") or "")


def fetch_cover(url: str, ffmpeg_path: str = "", timeout: float = 20.0) -> Optional[bytes]:
    """Download a thumbnail and return it as JPEG or PNG bytes.

    WebP (and anything else) is transcoded to JPEG with FFmpeg when a path is given.
    Returns ``None`` on any failure -- missing artwork must never fail a download.
    """
    if not url:
        return None
    try:
        import requests

        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        data = response.content
    except Exception as exc:  # noqa: BLE001 - artwork is strictly best-effort
        log.debug("Could not fetch cover art from %s: %s", url, exc)
        return None

    if not data:
        return None
    if data.startswith(JPEG_MAGIC) or data.startswith(PNG_MAGIC):
        return data
    if ffmpeg_path:
        converted = _transcode_image_to_jpeg(data, ffmpeg_path)
        if converted:
            return converted
    log.debug("Cover art at %s is in an unsupported format; skipping", url)
    return None


def _transcode_image_to_jpeg(data: bytes, ffmpeg_path: str) -> Optional[bytes]:
    """Pipe arbitrary image bytes through FFmpeg to get JPEG bytes back."""
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-frames:v", "1",
        "-f", "mjpeg", "-q:v", "2",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=False,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.debug("Cover transcode failed: %s", exc)
        return None
    if result.returncode == 0 and result.stdout.startswith(JPEG_MAGIC):
        return result.stdout
    return None


def cover_mime(data: bytes) -> str:
    return "image/png" if data.startswith(PNG_MAGIC) else "image/jpeg"


# ---------------------------------------------------------------------------
# Tag writing
# ---------------------------------------------------------------------------

def apply_tags(path: Path, meta: TrackMetadata, embed_cover: bool = True) -> bool:
    """Write ``meta`` into the audio file at ``path``.

    Returns ``True`` if tags were written. Tagging failures are logged and reported
    but never delete or invalidate the converted audio.
    """
    suffix = path.suffix.lower().lstrip(".")
    writer = _WRITERS.get(suffix)
    if writer is None:
        log.info("No tag writer for .%s; leaving %s untagged", suffix, path.name)
        return False
    try:
        writer(path, meta, embed_cover and meta.cover is not None)
        log.debug("Tagged %s", path.name)
        return True
    except Exception as exc:  # noqa: BLE001 - tagging must not fail the job
        log.warning("Could not tag %s: %s", path.name, exc)
        return False


# --- ID3 (mp3, raw aac, wav, aiff) -----------------------------------------
#
# Two distinct layouts share the ID3 frame vocabulary and must not be confused:
#   * MP3 and raw ADTS AAC carry an ID3v2 block at byte 0 of the file.
#   * WAV and AIFF carry ID3 *inside a container chunk*. Writing a bare ID3 block
#     at offset 0 of either would prepend garbage ahead of the RIFF/FORM header
#     and corrupt the file, so those go through their container class instead.

def _populate_id3(tags, meta: TrackMetadata, with_cover: bool) -> None:
    """Fill an ID3 tag object from ``meta``. Shared by both ID3 layouts."""
    from mutagen.id3 import APIC, COMM, TALB, TDRC, TIT2, TPE1, TPE2, TRCK

    tags.delall("APIC")
    if meta.title:
        tags.add(TIT2(encoding=3, text=meta.title))
    if meta.artist:
        tags.add(TPE1(encoding=3, text=meta.artist))
    if meta.album_artist:
        tags.add(TPE2(encoding=3, text=meta.album_artist))
    if meta.album:
        tags.add(TALB(encoding=3, text=meta.album))
    if meta.year:
        tags.add(TDRC(encoding=3, text=meta.year))
    track = _track_string(meta)
    if track:
        tags.add(TRCK(encoding=3, text=track))
    if meta.comment:
        tags.add(COMM(encoding=3, lang="eng", desc="", text=meta.comment))
    if with_cover and meta.cover:
        tags.add(
            APIC(
                encoding=3,
                mime=cover_mime(meta.cover),
                type=3,               # front cover
                desc="Cover",
                data=meta.cover,
            )
        )


def _write_id3_stream(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    """MP3 and raw ADTS AAC: an ID3v2 block at the head of the file."""
    from mutagen.id3 import ID3, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    _populate_id3(tags, meta, with_cover)
    # v2.3 has the widest player support.
    tags.save(str(path), v2_version=3)


def _write_id3_container(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    """WAV and AIFF: ID3 stored in the container's own tag chunk."""
    from mutagen.aiff import AIFF
    from mutagen.wave import WAVE

    container = AIFF if path.suffix.lower() in (".aiff", ".aif") else WAVE
    audio = container(str(path))
    if audio.tags is None:
        audio.add_tags()
    _populate_id3(audio.tags, meta, with_cover)
    audio.save()


# --- MP4 / M4A / ALAC -------------------------------------------------------

def _write_mp4(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(str(path))
    if audio.tags is None:
        audio.add_tags()

    tags = audio.tags
    if meta.title:
        tags["\xa9nam"] = [meta.title]
    if meta.artist:
        tags["\xa9ART"] = [meta.artist]
    if meta.album_artist:
        tags["aART"] = [meta.album_artist]
    if meta.album:
        tags["\xa9alb"] = [meta.album]
    if meta.year:
        tags["\xa9day"] = [meta.year]
    if meta.comment:
        tags["\xa9cmt"] = [meta.comment]
    if meta.track_number:
        tags["trkn"] = [(int(meta.track_number), int(meta.track_total or 0))]
    if with_cover and meta.cover:
        fmt = (MP4Cover.FORMAT_PNG if meta.cover.startswith(PNG_MAGIC)
               else MP4Cover.FORMAT_JPEG)
        tags["covr"] = [MP4Cover(meta.cover, imageformat=fmt)]
    audio.save()


# --- FLAC -------------------------------------------------------------------

def _write_flac(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(str(path))
    _fill_vorbis_comments(audio, meta)
    audio.clear_pictures()
    if with_cover and meta.cover:
        audio.add_picture(_flac_picture(meta.cover))
    audio.save()


def _flac_picture(cover: bytes):
    from mutagen.flac import Picture

    picture = Picture()
    picture.type = 3                    # front cover
    picture.mime = cover_mime(cover)
    picture.desc = "Cover"
    picture.data = cover
    return picture


# --- Ogg Vorbis / Opus ------------------------------------------------------

def _write_ogg_vorbis(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(str(path))
    _fill_vorbis_comments(audio, meta)
    if with_cover and meta.cover:
        audio["metadata_block_picture"] = [_encoded_picture_block(meta.cover)]
    audio.save()


def _write_opus(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    from mutagen.oggopus import OggOpus

    audio = OggOpus(str(path))
    _fill_vorbis_comments(audio, meta)
    if with_cover and meta.cover:
        audio["metadata_block_picture"] = [_encoded_picture_block(meta.cover)]
    audio.save()


def _fill_vorbis_comments(audio, meta: TrackMetadata) -> None:
    if meta.title:
        audio["title"] = meta.title
    if meta.artist:
        audio["artist"] = meta.artist
    if meta.album:
        audio["album"] = meta.album
    if meta.album_artist:
        audio["albumartist"] = meta.album_artist
    if meta.year:
        audio["date"] = meta.year
    if meta.track_number:
        audio["tracknumber"] = str(meta.track_number)
    if meta.track_total:
        audio["tracktotal"] = str(meta.track_total)
    if meta.comment:
        audio["comment"] = meta.comment


def _encoded_picture_block(cover: bytes) -> str:
    """Vorbis comments carry cover art as a base64 FLAC picture block."""
    return base64.b64encode(_flac_picture(cover).write()).decode("ascii")


# --- ASF / WMA --------------------------------------------------------------

def _write_asf(path: Path, meta: TrackMetadata, with_cover: bool) -> None:
    from mutagen.asf import ASF, ASFByteArrayAttribute

    audio = ASF(str(path))
    if meta.title:
        audio["Title"] = meta.title
    if meta.artist:
        audio["Author"] = meta.artist
    if meta.album:
        audio["WM/AlbumTitle"] = meta.album
    if meta.album_artist:
        audio["WM/AlbumArtist"] = meta.album_artist
    if meta.year:
        audio["WM/Year"] = meta.year
    if meta.track_number:
        audio["WM/TrackNumber"] = str(meta.track_number)
    if meta.comment:
        audio["Description"] = meta.comment
    if with_cover and meta.cover:
        audio["WM/Picture"] = [ASFByteArrayAttribute(_asf_picture(meta.cover))]
    audio.save()


def _asf_picture(cover: bytes) -> bytes:
    """Pack cover art into the WM/Picture binary layout."""
    mime = cover_mime(cover).encode("utf-16-le") + b"\x00\x00"
    description = "Cover".encode("utf-16-le") + b"\x00\x00"
    return (
        struct.pack("<b", 3)                 # picture type: front cover
        + struct.pack("<i", len(cover))      # image data length
        + mime
        + description
        + cover
    )


def _track_string(meta: TrackMetadata) -> str:
    if not meta.track_number:
        return ""
    if meta.track_total:
        return f"{meta.track_number}/{meta.track_total}"
    return str(meta.track_number)


_WRITERS = {
    "mp3": _write_id3_stream,
    "aac": _write_id3_stream,      # ID3v2 prepended to the ADTS stream
    "aiff": _write_id3_container,
    "aif": _write_id3_container,
    "wav": _write_id3_container,
    "m4a": _write_mp4,
    "mp4": _write_mp4,
    "flac": _write_flac,
    "ogg": _write_ogg_vorbis,
    "opus": _write_opus,
    "wma": _write_asf,
}
