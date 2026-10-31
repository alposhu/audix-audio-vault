"""What audix adds to the pages inside the embedded browser.

Two things only: a small Download and Queue pair over whichever video thumbnail the
pointer is on, and a report of what the current page is showing, so the dock below
the browser can name it. Doing this with one floating element and pointer events,
rather than editing each card, is what keeps it working when YouTube restyles its
layout: it needs nothing from the page except links that wrap a thumbnail.

Isolation is the security boundary here. The script runs in Chromium's isolated
application world and the channel is registered only in that world, so scripts
belonging to the pages themselves can neither see nor call :class:`PageBridge`.
Everything arriving from the script is still treated as untrusted, because the DOM
it reads from is the page's own.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QFile, QIODevice, QObject, Signal, Slot

from audix.core import links
from audix.ui.tokens import COLORS, FILL_TEXT

log = logging.getLogger("audix.ui.bridge")

#: Longest text accepted from a page. Titles are short; anything larger is not one.
_MAX_FIELD = 400
_MAX_REPORT = 8192


@dataclass(frozen=True)
class PageInfo:
    """What the page script could read about the current page."""

    url: str = ""
    title: str = ""
    channel: str = ""
    duration: Optional[float] = None
    list_title: str = ""
    list_count: Optional[int] = None


@dataclass(frozen=True)
class PageLink:
    """A video the user picked from the page, and whatever the card said about it."""

    url: str
    title: str = ""
    channel: str = ""
    duration: Optional[float] = None


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())[:_MAX_FIELD]


def _number(value: object) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 10 ** 7 else None


class PageBridge(QObject):
    """The Python object the isolated page script talks to."""

    page_reported = Signal(object)        # PageInfo
    download_requested = Signal(object)   # PageLink
    queue_requested = Signal(object)      # PageLink
    list_requested = Signal(str)          # URL of a Mix or playlist

    @Slot(str)
    def report(self, payload: str) -> None:
        if len(payload) > _MAX_REPORT:
            return
        try:
            raw = json.loads(payload)
        except ValueError:
            return
        if not isinstance(raw, dict):
            return
        url = str(raw.get("url") or "")
        if not links.parse(url).is_youtube:
            return
        count = _number(raw.get("listCount"))
        self.page_reported.emit(PageInfo(
            url=url,
            title=_clean(raw.get("title")),
            channel=_clean(raw.get("channel")),
            duration=_number(raw.get("duration")),
            list_title=_clean(raw.get("listTitle")),
            list_count=int(count) if count else None,
        ))

    @Slot(str, str, str, str)
    def download(self, url: str, title: str, channel: str, duration: str) -> None:
        picked = self._read(url, title, channel, duration)
        if picked is not None:
            self.download_requested.emit(picked)

    @Slot(str, str, str, str)
    def enqueue(self, url: str, title: str, channel: str, duration: str) -> None:
        picked = self._read(url, title, channel, duration)
        if picked is not None:
            self.queue_requested.emit(picked)

    @Slot(str)
    def enqueueList(self, url: str) -> None:  # noqa: N802 - called from the page script
        if links.parse(url).has_list:
            self.list_requested.emit(url)

    @staticmethod
    def _read(url: str, title: str, channel: str, duration: str) -> Optional[PageLink]:
        if not links.parse(url).has_video:
            log.debug("Ignoring a page request that names no video: %s", url[:200])
            return None
        return PageLink(url=url, title=_clean(title), channel=_clean(channel),
                        duration=_number(duration))


def install(page, bridge: PageBridge) -> bool:
    """Attach the bridge and the page script to ``page``. Returns whether it worked."""
    try:
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineCore import QWebEngineScript
    except ImportError as exc:
        log.warning("Page tools unavailable: %s", exc)
        return False

    library = _read_channel_library()
    if not library:
        log.warning("qwebchannel.js is missing; the page buttons are unavailable")
        return False

    channel = QWebChannel(page)
    channel.registerObject("audix", bridge)
    page.setWebChannel(channel, QWebEngineScript.ApplicationWorld)

    script = QWebEngineScript()
    script.setName("audix-page-tools")
    script.setSourceCode(library + "\n" + _page_script())
    script.setInjectionPoint(QWebEngineScript.DocumentReady)
    script.setWorldId(QWebEngineScript.ApplicationWorld)
    script.setRunsOnSubFrames(False)
    page.scripts().insert(script)
    return True


def _read_channel_library() -> str:
    resource = QFile(":/qtwebchannel/qwebchannel.js")
    if not resource.open(QIODevice.ReadOnly):
        return ""
    source = bytes(resource.readAll()).decode("utf-8")
    resource.close()
    return source


def _page_script() -> str:
    source = _PAGE_SCRIPT
    for token, value in (
        ("%%PLATE%%", COLORS["surface"]),
        ("%%EDGE%%", COLORS["border_hi"]),
        ("%%INK%%", COLORS["ink"]),
        ("%%KEY%%", COLORS["surface_3"]),
        ("%%LIT%%", COLORS["primary"]),
        ("%%LIT_HI%%", COLORS["primary_hi"]),
        ("%%LIT_INK%%", FILL_TEXT["primary"]),
    ):
        source = source.replace(token, value)
    return source


_PAGE_SCRIPT = r"""
(() => {
  if (!/(^|\.)youtube\.com$/.test(location.hostname) || window.__audixTools) return;
  window.__audixTools = true;

  let host = null;
  new QWebChannel(qt.webChannelTransport, (channel) => {
    host = channel.objects.audix;
    scheduleReports();
  });

  // ------------------------------------------------------------ page report
  const text = (selector, root = document) =>
    (root.querySelector(selector)?.textContent || "").trim();

  function firstText(selectors, root = document) {
    for (const selector of selectors) {
      const found = text(selector, root);
      if (found) return found;
    }
    return "";
  }

  function parseClock(value) {
    const parts = (value || "").trim().split(":").map(Number);
    if (parts.length < 2 || parts.some(Number.isNaN)) return 0;
    return parts.reduce((total, part) => total * 60 + part, 0);
  }

  // A tile can wear several badges (4K, Mix, a live marker), and YouTube repeats text
  // inside them, so look through all of them for anything shaped like a length.
  const CLOCK = /\b(?:\d{1,2}:)?\d{1,2}:\d{2}\b/;

  function stampedLength(card) {
    const stamps = card.querySelectorAll(
      "ytd-thumbnail-overlay-time-status-renderer, yt-thumbnail-badge-view-model, " +
      "badge-shape, .yt-badge-shape__text");
    for (const stamp of stamps) {
      const clock = (stamp.textContent || "").match(CLOCK);
      if (clock) return parseClock(clock[0]);
    }
    return 0;
  }

  function videoDuration() {
    const player = document.querySelector("#movie_player");
    if (player?.classList.contains("ad-showing")) return 0;
    const video = document.querySelector("video.html5-main-video, video");
    return video && Number.isFinite(video.duration) ? video.duration : 0;
  }

  function watchedVideoId() {
    const url = new URL(location.href);
    return url.searchParams.get("v") || (url.pathname.match(/^\/shorts\/([\w-]{11})/) || [])[1] || "";
  }

  function pageTitleFallback() {
    return document.title.replace(/^\(\d+\)\s*/, "").replace(/\s*-\s*YouTube$/, "");
  }

  function listInfo() {
    const panel = document.querySelector("ytd-playlist-panel-renderer#playlist:not([hidden])");
    if (panel) {
      const title = firstText(["#header-description h3 yt-formatted-string", "h3 yt-formatted-string", ".title"], panel);
      const counter = text(".index-message, #publisher-container span:last-child", panel);
      const total = counter.match(/\/\s*([\d.,]+)/);
      return { title, count: total ? Number(total[1].replace(/[.,]/g, "")) : 0 };
    }
    if (location.pathname === "/playlist") {
      const title = firstText(["yt-page-header-renderer h1", "ytd-playlist-header-renderer h1",
                               "h1.dynamic-text-view-model-wiz__h1"]) || pageTitleFallback();
      const stats = firstText(["yt-content-metadata-view-model", "ytd-playlist-byline-renderer",
                               "ytd-playlist-sidebar-primary-info-renderer #stats"]);
      const total = stats.match(/([\d.,]+)\s+(?:video|track|song)/i);
      return { title, count: total ? Number(total[1].replace(/[.,]/g, "")) : 0 };
    }
    return { title: "", count: 0 };
  }

  function report() {
    if (!host) return;
    const videoId = watchedVideoId();
    const flexy = document.querySelector("ytd-watch-flexy");
    // During in-app navigation the old title lingers; only trust it once it matches.
    const fresh = !videoId || !flexy || flexy.getAttribute("video-id") === videoId;
    const list = listInfo();
    host.report(JSON.stringify({
      url: location.href,
      title: fresh ? firstText(["ytd-watch-metadata h1 yt-formatted-string", "ytd-watch-metadata h1",
                                "ytd-reel-video-renderer[is-active] h2"]) : "",
      channel: fresh ? firstText(["ytd-watch-metadata ytd-channel-name a",
                                  "ytd-watch-metadata #owner ytd-channel-name",
                                  "ytd-reel-video-renderer[is-active] ytd-channel-name a"]) : "",
      duration: fresh ? videoDuration() : 0,
      listTitle: list.title,
      listCount: list.count,
    }));
  }

  let reportTimers = [];
  function scheduleReports() {
    reportTimers.forEach(clearTimeout);
    reportTimers = [150, 800, 2000, 4500].map((delay) => setTimeout(report, delay));
  }

  for (const name of ["yt-navigate-finish", "yt-page-data-updated"]) {
    document.addEventListener(name, scheduleReports);
  }
  document.addEventListener("loadedmetadata", report, true);

  // --------------------------------------------------------- thumbnail keys
  const CSS = `
    :host { all: initial; }
    .bar {
      display: flex; gap: 4px; padding: 3px;
      background: %%PLATE%%; border: 1px solid %%EDGE%%; border-radius: 4px;
      box-shadow: 0 4px 14px rgba(0, 0, 0, .45);
      font: 600 12px "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
    }
    button {
      all: unset; box-sizing: border-box; cursor: pointer;
      display: inline-flex; align-items: center; gap: 5px;
      height: 26px; padding: 0 9px; border-radius: 3px;
      color: %%INK%%; background: %%KEY%%; white-space: nowrap;
    }
    button:hover { filter: brightness(1.18); }
    button:focus-visible { outline: 2px solid %%LIT%%; outline-offset: 1px; }
    button.primary { color: %%LIT_INK%%; background: %%LIT%%; }
    button.primary:hover { background: %%LIT_HI%%; filter: none; }
    svg { width: 14px; height: 14px; fill: none; stroke: currentColor;
          stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
    .compact span { display: none; }
    .compact button { padding: 0 7px; }
  `;

  const SHAPES = {
    download: ["M12 4v11", "M7 10.5l5 5 5-5", "M4.5 15.5v4h15v-4"],
    plus: ["M12 5v14", "M5 12h14"],
    check: ["M4.5 12.5l5 5 10-11"],
  };

  function makeIcon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    for (const shape of SHAPES[name]) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", shape);
      svg.append(path);
    }
    return svg;
  }

  function makeKey(icon, primary, onClick) {
    const key = document.createElement("button");
    if (primary) key.className = "primary";
    const caption = document.createElement("span");
    key.append(makeIcon(icon), caption);
    key.label = (text, title) => {
      caption.textContent = text;
      key.title = title;
      key.setAttribute("aria-label", title);
    };
    key.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!target || !host) return;
      onClick(target);
      const resting = caption.textContent;
      key.replaceChildren(makeIcon("check"), caption);
      caption.textContent = "Added";
      setTimeout(() => {
        key.replaceChildren(makeIcon(icon), caption);
        caption.textContent = resting;
      }, 1100);
    });
    return key;
  }

  const shell = document.createElement("div");
  shell.style.cssText = "position:fixed;top:0;left:0;z-index:2147483647;display:none;";
  const root = shell.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = CSS;
  const bar = document.createElement("div");
  bar.className = "bar";
  const downloadKey = makeKey("download", true,
    (t) => host.download(t.url, t.title, t.channel, String(t.duration)));
  const queueKey = makeKey("plus", false, (t) => {
    if (t.list) host.enqueueList(t.url);
    else host.enqueue(t.url, t.title, t.channel, String(t.duration));
  });
  downloadKey.label("Download", "Download this audio now");
  bar.append(downloadKey, queueKey);
  root.append(style, bar);
  document.documentElement.append(shell);

  // A Mix or playlist tile links to its first video, but what it shows is the list.
  // Offering to download "this" would quietly mean one track under the list's name,
  // so a list tile says what it is and goes to the Queue, where you choose from it.
  //
  // The link alone cannot tell: YouTube adds list=RD... to ordinary music videos in
  // search results too. What separates them is the stamp on the thumbnail. A video
  // shows its length; a list shows a word, in whatever language the page is in.
  function listKind(href, duration) {
    if (duration > 0) return "";
    const url = new URL(href);
    const list = url.searchParams.get("list");
    if (!list || url.searchParams.has("index")) return "";
    return /^RD(?!CLAK5uy_)/.test(list) ? "Mix" : "playlist";
  }

  function labelKeys(kind) {
    downloadKey.style.display = kind ? "none" : "";
    if (kind) queueKey.label(`Queue ${kind}`, `Add this ${kind} to your Queue to choose from it`);
    else queueKey.label("Queue", "Add to your Queue");
  }

  const CARDS = [
    "ytd-rich-item-renderer", "ytd-video-renderer", "ytd-compact-video-renderer",
    "ytd-grid-video-renderer", "ytd-playlist-video-renderer",
    "ytd-playlist-panel-video-renderer", "yt-lockup-view-model",
    "ytm-shorts-lockup-view-model", "ytd-reel-item-renderer",
  ].join(",");

  function videoLink(anchor) {
    const href = anchor.href || "";
    return /[?&]v=[\w-]{11}/.test(href) || /\/shorts\/[\w-]{11}/.test(href) ? href : "";
  }

  function hasThumbnail(anchor) {
    return !!anchor.querySelector("img, yt-image, yt-thumbnail-view-model, ytd-thumbnail");
  }

  function describe(anchor) {
    const card = anchor.closest(CARDS) || anchor.parentElement;
    const titled = card.querySelector("#video-title[title], a#video-title, #video-title, h3 a[title], h3");
    const title = (titled?.getAttribute("title") || titled?.textContent ||
                   anchor.getAttribute("title") || anchor.getAttribute("aria-label") || "").trim();
    const channel = firstText(["ytd-channel-name #text", "#channel-name #text", "ytd-channel-name a",
                               ".yt-content-metadata-view-model__metadata-text",
                               ".yt-content-metadata-view-model-wiz__metadata-text"], card);
    return { title, channel, duration: stampedLength(card) };
  }

  let target = null;
  let overBar = false;

  function place(anchor) {
    const box = anchor.getBoundingClientRect();
    bar.classList.toggle("compact", box.width < 210);
    shell.style.transform = `translate(${Math.round(box.left + 6)}px, ${Math.round(box.top + 6)}px)`;
  }

  function videoIdOf(href) {
    const url = new URL(href);
    return url.searchParams.get("v") || url.pathname.split("/").pop();
  }

  function show(anchor, url) {
    if (target && (target.anchor === anchor || videoIdOf(target.url) === videoIdOf(url))) {
      return;     // the preview player brings its own link to the same video
    }
    const box = anchor.getBoundingClientRect();
    if (box.width < 80 || box.height < 45) return;
    const details = describe(anchor);
    const list = listKind(url, details.duration);
    target = { anchor, url, list, box, ...details };
    labelKeys(list);
    place(anchor);
    shell.style.display = "block";
  }

  function hide() {
    target = null;
    overBar = false;
    shell.style.display = "none";
  }

  bar.addEventListener("mouseenter", () => { overBar = true; });
  bar.addEventListener("mouseleave", () => { overBar = false; });

  document.addEventListener("mouseover", (event) => {
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!anchor) return;
    const url = videoLink(anchor);
    if (url && hasThumbnail(anchor)) show(anchor, url);
  }, { capture: true, passive: true });

  // After a moment YouTube swaps a hovered thumbnail for its own preview player,
  // which collapses the thumbnail to nothing. So leaving is judged against the box
  // measured when the keys appeared, never against the element as it is now.
  document.addEventListener("mousemove", (event) => {
    if (!target || overBar) return;
    const { box } = target;
    const inside = event.clientX >= box.left && event.clientX <= box.right &&
                   event.clientY >= box.top && event.clientY <= box.bottom;
    if (!inside) hide();
  }, { capture: true, passive: true });

  // Only the page itself: previews and carousels scroll internally all the time.
  document.addEventListener("scroll", (event) => {
    if (target && event.target === document) hide();
  }, { capture: true, passive: true });
})();
"""
