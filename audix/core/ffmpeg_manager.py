"""FFmpeg dependency management: detect, download, extract, register.

Runs on application launch. If ``ffmpeg`` and ``ffprobe`` are not already usable
the correct static build for the host OS/architecture is fetched, unpacked into
``~/.audix/bin``, and that directory is prepended to ``os.environ["PATH"]``.

Nothing in the download pipeline is allowed to start until :meth:`FFmpegManager.ensure`
has returned ``True`` — the app gates on it explicitly.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from audix.utils import paths
from audix.utils.proc import run_capture

log = logging.getLogger("audix.ffmpeg")

# (stage description, 0..100 percentage; -1 means indeterminate)
ProgressCallback = Callable[[str, float], None]

_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
_EVERMEET = "https://evermeet.cx/ffmpeg/getrelease"

REQUIRED_BINARIES = ("ffmpeg", "ffprobe")


class FFmpegError(RuntimeError):
    """Raised when FFmpeg cannot be located, downloaded, or verified."""


#: Environment variable letting a user pin the expected SHA-256 of the FFmpeg
#: archive. See :func:`_http_download` for why this is opt-in rather than a
#: hard-coded constant.
SHA256_ENV = "AUDIX_FFMPEG_SHA256"


@dataclass
class BuildSpec:
    """Where to fetch a static build for this platform, and how to unpack it."""

    urls: List[str] = field(default_factory=list)
    kind: str = "zip"          # "zip" | "tar.xz"
    description: str = ""
    #: Expected SHA-256 of the archive, when one is known. Left unset for the
    #: rolling "latest" builds, whose digest changes on every upstream release.
    sha256: Optional[str] = None


def _normalise_arch() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return machine or "unknown"


def resolve_build_spec() -> BuildSpec:
    """Pick the correct static FFmpeg build for the running host."""
    system = platform.system().lower()
    arch = _normalise_arch()

    if system == "windows":
        slug = "winarm64" if arch == "arm64" else "win64"
        return BuildSpec(
            urls=[f"{_BTBN}/ffmpeg-master-latest-{slug}-gpl.zip"],
            kind="zip",
            description=f"Windows {arch}",
        )

    if system == "linux":
        slug = "linuxarm64" if arch == "arm64" else "linux64"
        return BuildSpec(
            urls=[f"{_BTBN}/ffmpeg-master-latest-{slug}-gpl.tar.xz"],
            kind="tar.xz",
            description=f"Linux {arch}",
        )

    if system == "darwin":
        # evermeet.cx publishes ffmpeg and ffprobe as two separate archives.
        # These are x86_64 builds; they run on Apple Silicon under Rosetta 2.
        return BuildSpec(
            urls=[f"{_EVERMEET}/zip", f"{_EVERMEET}/ffprobe/zip"],
            kind="zip",
            description=f"macOS {arch}",
        )

    raise FFmpegError(
        f"No prebuilt FFmpeg is available for {platform.system()} ({arch}). "
        "Please install ffmpeg and ffprobe manually and ensure they are on PATH."
    )


class FFmpegManager:
    """Locates or installs FFmpeg, and exposes the resolved binary paths."""

    def __init__(self, preferred_dir: str = "") -> None:
        self.preferred_dir = Path(preferred_dir).expanduser() if preferred_dir else None
        self.ffmpeg_path: Optional[Path] = None
        self.ffprobe_path: Optional[Path] = None

    # ------------------------------------------------------------------ state
    @property
    def ready(self) -> bool:
        return self.ffmpeg_path is not None and self.ffprobe_path is not None

    def ffmpeg(self) -> str:
        if not self.ffmpeg_path:
            raise FFmpegError("FFmpeg is not available yet.")
        return str(self.ffmpeg_path)

    def ffprobe(self) -> str:
        if not self.ffprobe_path:
            raise FFmpegError("ffprobe is not available yet.")
        return str(self.ffprobe_path)

    def bin_directory(self) -> Optional[Path]:
        return self.ffmpeg_path.parent if self.ffmpeg_path else None

    # --------------------------------------------------------------- locating
    def _candidate_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        if self.preferred_dir:
            dirs.append(self.preferred_dir)
        dirs.append(paths.bin_dir())
        return dirs

    def locate(self) -> bool:
        """Look for a usable pair of binaries. Returns True when both are found.

        Search order: user-configured directory, ``~/.audix/bin``, then ``PATH``.
        A candidate is only accepted if it actually executes.
        """
        found: dict = {}
        for stem in REQUIRED_BINARIES:
            exe = paths.executable_name(stem)
            candidate: Optional[Path] = None

            for directory in self._candidate_dirs():
                path = directory / exe
                if path.is_file():
                    candidate = path
                    break

            if candidate is None:
                on_path = shutil.which(stem)
                if on_path:
                    candidate = Path(on_path)

            if candidate is None or not self._verify(candidate):
                return False
            found[stem] = candidate

        self.ffmpeg_path = found["ffmpeg"]
        self.ffprobe_path = found["ffprobe"]
        self.register_path()
        log.info("Using ffmpeg at %s", self.ffmpeg_path)
        return True

    @staticmethod
    def _verify(binary: Path) -> bool:
        """Confirm a binary runs and reports a version."""
        try:
            result = run_capture([str(binary), "-version"], timeout=20)
        except (OSError, Exception) as exc:  # noqa: BLE001 - includes TimeoutExpired
            log.debug("Verification failed for %s: %s", binary, exc)
            return False
        ok = result.returncode == 0 and "version" in (result.stdout or "").lower()
        if not ok:
            log.debug("Verification rejected %s (rc=%s)", binary, result.returncode)
        return ok

    def register_path(self) -> None:
        """Prepend our binary directory to ``PATH`` for this process and children."""
        directory = self.bin_directory()
        if directory is None:
            return
        entry = str(directory)
        current = os.environ.get("PATH", "")
        parts = current.split(os.pathsep) if current else []
        if entry not in parts:
            os.environ["PATH"] = os.pathsep.join([entry, *parts]) if parts else entry
            log.info("Registered %s on PATH", entry)

    # -------------------------------------------------------------- installing
    def ensure(self, progress: Optional[ProgressCallback] = None) -> bool:
        """Guarantee FFmpeg is available, downloading it if required.

        Returns ``True`` on success. Raises :class:`FFmpegError` if the platform is
        unsupported or the install could not be completed.
        """
        report = progress or (lambda _stage, _pct: None)

        report("Checking for audio codecs…", -1)
        if self.locate():
            report("Audio codecs ready.", 100)
            return True

        log.info("FFmpeg not found; starting first-time setup")
        spec = resolve_build_spec()
        report(f"Downloading FFmpeg for {spec.description}…", 0)
        self._download_and_install(spec, report)

        # Force a re-scan restricted to our own bin directory.
        self.preferred_dir = paths.bin_dir()
        if not self.locate():
            raise FFmpegError(
                "FFmpeg was downloaded but could not be verified. "
                f"Check {paths.bin_dir()} and your antivirus/quarantine settings."
            )
        report("Audio codecs ready.", 100)
        return True

    def _download_and_install(self, spec: BuildSpec, report: ProgressCallback) -> None:
        target = paths.bin_dir()
        target.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="audix-ffmpeg-") as tmp:
            tmpdir = Path(tmp)
            extracted_root = tmpdir / "extracted"
            extracted_root.mkdir()

            total_archives = len(spec.urls)
            for idx, url in enumerate(spec.urls):
                archive = tmpdir / f"part{idx}"
                base = idx / total_archives * 100.0
                span = 100.0 / total_archives

                def on_bytes(fraction: float, _base=base, _span=span) -> None:
                    report("First Time Setup: Downloading required audio codecs…",
                           _base + fraction * _span * 0.85)

                # Only the single-archive platforms can carry a pinned digest;
                # macOS fetches ffmpeg and ffprobe separately.
                expected = spec.sha256 if total_archives == 1 else None
                _http_download(url, archive, on_bytes, expected_sha256=expected)
                report("Extracting audio codecs…", base + span * 0.9)
                _extract(archive, extracted_root, spec.kind)

            report("Installing audio codecs…", 96)
            installed = _collect_binaries(extracted_root, target)

        missing = [b for b in REQUIRED_BINARIES if b not in installed]
        if missing:
            raise FFmpegError(
                "The downloaded FFmpeg package did not contain: "
                + ", ".join(missing)
            )
        log.info("Installed %s into %s", ", ".join(sorted(installed)), target)


# ---------------------------------------------------------------------------
# Download / extract helpers (module-level so they are independently testable)
# ---------------------------------------------------------------------------

def _http_download(url: str, destination: Path, on_progress: Callable[[float], None],
                   expected_sha256: Optional[str] = None) -> str:
    """Stream ``url`` to ``destination``, reporting progress. Returns the SHA-256.

    Integrity, stated honestly:

    * Transport is HTTPS with certificate verification left on, so the download
      is authenticated to the host and cannot be modified in transit.
    * The SHA-256 is always computed and logged, so a user can compare builds
      across machines and spot an unexpected change.
    * If an expected digest is supplied - via :attr:`BuildSpec.sha256` or the
      ``AUDIX_FFMPEG_SHA256`` environment variable - it is enforced, and a
      mismatch aborts before anything is extracted or executed.

    No digest is hard-coded for the default source, because it points at a
    rolling "latest" release whose content changes upstream; a pinned constant
    would break the installer on every FFmpeg update. Fetching a checksum file
    from the same host would add no protection either, since an attacker able
    to alter the archive could alter the checksum beside it. Users who want a
    hard guarantee should pin ``AUDIX_FFMPEG_SHA256`` to a digest they trust.
    """
    import hashlib

    import requests

    log.info("Downloading %s", url)
    headers = {"User-Agent": "audix (+https://github.com/alposhu/audix-audio-vault)"}
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=60, headers=headers,
                          allow_redirects=True) as response:
            response.raise_for_status()
            # Refuse to follow a downgrade to plaintext via redirect.
            if not response.url.lower().startswith("https://"):
                raise FFmpegError(
                    f"Refusing to download FFmpeg over an insecure connection: "
                    f"{response.url}"
                )
            total = int(response.headers.get("Content-Length") or 0)
            written = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if total > 0:
                        on_progress(min(written / total, 1.0))
    except requests.RequestException as exc:
        raise FFmpegError(
            f"Could not download FFmpeg from {url}: {exc}. "
            "Check your internet connection or firewall and try again."
        ) from exc

    if destination.stat().st_size < 1024:
        raise FFmpegError(f"Downloaded FFmpeg archive from {url} is empty or truncated.")

    actual = digest.hexdigest()
    log.info("FFmpeg archive SHA-256: %s", actual)

    wanted = (expected_sha256 or os.environ.get(SHA256_ENV) or "").strip().lower()
    if wanted:
        if actual != wanted:
            destination.unlink(missing_ok=True)
            raise FFmpegError(
                "FFmpeg download failed its integrity check and was discarded.\n"
                f"  expected: {wanted}\n"
                f"  actual  : {actual}\n"
                "Nothing was extracted or executed."
            )
        log.info("FFmpeg archive matched the expected SHA-256")
    return actual


def _is_within(root: Path, candidate: Path) -> bool:
    """Guard against path-traversal entries in downloaded archives."""
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _extract(archive: Path, destination: Path, kind: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "zip" or zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as zf:
                for member in zf.infolist():
                    out = destination / member.filename
                    if not _is_within(destination, out):
                        log.warning("Skipping unsafe archive entry %s", member.filename)
                        continue
                    zf.extract(member, destination)
        else:
            with tarfile.open(archive, "r:*") as tf:
                for member in tf.getmembers():
                    out = destination / member.name
                    if not _is_within(destination, out):
                        log.warning("Skipping unsafe archive entry %s", member.name)
                        continue
                    tf.extract(member, destination)
    except (zipfile.BadZipFile, tarfile.TarError, OSError) as exc:
        raise FFmpegError(f"Could not extract the FFmpeg archive: {exc}") from exc


def _collect_binaries(search_root: Path, target: Path) -> set:
    """Copy every required binary found under ``search_root`` into ``target``."""
    installed: set = set()
    wanted = {paths.executable_name(stem): stem for stem in REQUIRED_BINARIES}

    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        stem = wanted.get(path.name)
        if stem is None or stem in installed:
            continue
        destination = target / path.name
        try:
            shutil.copy2(path, destination)
            _make_executable(destination)
            installed.add(stem)
        except OSError as exc:
            raise FFmpegError(f"Could not install {path.name}: {exc}") from exc
    return installed


def _make_executable(path: Path) -> None:
    if os.name == "nt":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def probe_duration(ffprobe: str, media: Path) -> Optional[float]:
    """Return media duration in seconds, or ``None`` if it cannot be determined."""
    result = run_capture(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return None
    try:
        value = float((result.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def probe_audio_stream(ffprobe: str, media: Path) -> Tuple[Optional[str], Optional[int]]:
    """Return ``(codec_name, bitrate_bps)`` for the first audio stream."""
    result = run_capture(
        [
            ffprobe, "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,bit_rate",
            "-of", "default=noprint_wrappers=1",
            str(media),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return None, None

    codec: Optional[str] = None
    bitrate: Optional[int] = None
    for line in (result.stdout or "").splitlines():
        key, _, value = line.partition("=")
        value = value.strip()
        if key == "codec_name" and value and value != "N/A":
            codec = value
        elif key == "bit_rate" and value.isdigit():
            bitrate = int(value)
    return codec, bitrate
