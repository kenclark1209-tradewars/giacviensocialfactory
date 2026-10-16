"""Extract original content from a pasted video/page link.

Step 1 of the "remix link" pipeline: given a YouTube / TikTok / Instagram /
Facebook / X / generic web URL, pull the title, author, description,
thumbnail and — where available — captions/transcript, via oEmbed and
OpenGraph metadata. No video bytes are ever downloaded: this module only
reads public metadata so the original can be *rewritten*, not re-uploaded.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "FrameWeaver-Remix/1.0 (+https://github.com/kenclark1209-tradewars/giacviensocialfactory)"
FETCH_TIMEOUT_S = 15.0
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 6000
CACHE_TTL_S = 10 * 60

_YT_ID_RE = re.compile(r"(?:v=|/shorts/|/embed/|youtu\.be/)([A-Za-z0-9_-]{11})")
_TT_ID_RE = re.compile(r"/video/(\d{5,})")

_cache: dict[str, tuple[float, "LinkContent"]] = {}


@dataclass
class LinkContent:
    """Public metadata extracted from a link. All fields optional except url/platform."""

    url: str
    platform: str  # youtube | tiktok | instagram | facebook | x | web
    video_id: str | None = None
    title: str | None = None
    author: str | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    duration_s: float | None = None
    captions: str | None = None
    captions_lang: str | None = None
    page_text: str | None = None
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "tiktok.com" in host:
        return "tiktok"
    if "instagram.com" in host:
        return "instagram"
    if "facebook.com" in host or "fb.watch" in host:
        return "facebook"
    if "twitter.com" in host or "x.com" in host:
        return "x"
    return "web"


def _youtube_id(url: str) -> str | None:
    match = _YT_ID_RE.search(url)
    return match.group(1) if match else None


async def _assert_public_url(url: str) -> str:
    """SSRF guard: only http(s), and the host must resolve to a public IP."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Link phải bắt đầu bằng http:// hoặc https://")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith(".local"):
        raise ValueError("Không hỗ trợ link nội bộ (localhost).")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError as exc:
        raise ValueError(f"Không phân giải được địa chỉ của link: {host}") from exc
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError("Không hỗ trợ link trỏ về địa chỉ mạng nội bộ.")
    return url


class _MetaParser(HTMLParser):
    """Collect OpenGraph / Twitter / title / JSON-LD metadata from HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: str | None = None
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: list[str] = []
        self.jsonld: list[dict] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._skip = True
            if tag == "script" and attrs_d.get("type") == "application/ld+json":
                self._in_jsonld = True
                self._jsonld_buf = []
            return
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            key = attrs_d.get("property") or attrs_d.get("name")
            content = attrs_d.get("content")
            if key and content and key not in self.meta:
                self.meta[key.strip().lower()] = content.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False
            if tag == "script" and self._in_jsonld:
                self._in_jsonld = False
                try:
                    data = json.loads("".join(self._jsonld_buf))
                except (json.JSONDecodeError, ValueError):
                    data = None
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        self.jsonld.append(item)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data
        if self._in_jsonld:
            self._jsonld_buf.append(data)


class _TextParser(HTMLParser):
    """Collect visible text, skipping scripts/styles."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | None:
    for attempt in range(2):
        try:
            resp = await client.get(url, timeout=FETCH_TIMEOUT_S)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403, 404):
                return None
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("oEmbed attempt %d failed for %s: %s", attempt, url, exc)
            await asyncio.sleep(0.5 * (attempt + 1))
    return None


async def _get_text(client: httpx.AsyncClient, url: str, *, max_bytes: int = MAX_HTML_BYTES) -> str | None:
    try:
        async with client.stream("GET", url, timeout=FETCH_TIMEOUT_S) as resp:
            if resp.status_code != 200:
                return None
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes(65536):
                size += len(chunk)
                if size > max_bytes:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
        encoding = resp.encoding or "utf-8"
        return raw.decode(encoding, errors="replace")
    except httpx.HTTPError as exc:
        logger.debug("GET failed for %s: %s", url, exc)
        return None


def _parse_caption_tracks(xml_text: str) -> list[dict]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    tracks = []
    for track in root.findall("track"):
        tracks.append({k: track.get(k) for k in ("lang_code", "name", "kind") if track.get(k)})
    return tracks


def _pick_caption_lang(tracks: list[dict]) -> str | None:
    if not tracks:
        return None
    langs = [t.get("lang_code", "") for t in tracks]
    for prefix in ("vi", "en"):
        for lang in langs:
            if lang == prefix or lang.startswith(prefix + "-"):
                return lang
    return langs[0]


def _parse_transcript(xml_text: str) -> str | None:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None
    parts = []
    for node in root.findall("text"):
        text = html.unescape("".join(node.itertext())).strip()
        if text:
            parts.append(text)
    joined = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return joined[:MAX_TEXT_CHARS] if joined else None


async def _youtube_captions(client: httpx.AsyncClient, video_id: str) -> tuple[str | None, str | None]:
    list_xml = await _get_text(
        client, f"https://video.google.com/timedtext?type=list&v={video_id}", max_bytes=65536
    )
    if not list_xml:
        return None, None
    lang = _pick_caption_lang(_parse_caption_tracks(list_xml))
    if not lang:
        return None, None
    transcript_xml = await _get_text(
        client, f"https://video.google.com/timedtext?lang={lang}&v={video_id}", max_bytes=512 * 1024
    )
    if not transcript_xml:
        return None, None
    return _parse_transcript(transcript_xml), lang


def _jsonld_pick(jsonld: list[dict]) -> dict:
    """Pick the most useful JSON-LD node (VideoObject / Article / NewsArticle)."""
    for item in jsonld:
        types = item.get("@type")
        types = [types] if isinstance(types, str) else (types or [])
        if any(t in ("VideoObject", "Article", "NewsArticle", "BlogPosting") for t in types):
            return item
    return jsonld[0] if jsonld else {}


async def _extract_generic(client: httpx.AsyncClient, url: str, platform: str) -> LinkContent:
    content = LinkContent(url=url, platform=platform)
    page = await _get_text(client, url)
    if not page:
        raise ValueError("Không tải được trang. Link có thể đã xóa, ở chế độ riêng tư, hoặc chặn truy cập tự động.")
    parser = _MetaParser()
    try:
        parser.feed(page[:MAX_HTML_BYTES])
    except Exception as exc:  # malformed HTML must not kill the pipeline
        logger.debug("HTML parse warning: %s", exc)
    meta = parser.meta
    node = _jsonld_pick(parser.jsonld)

    def first(*keys: str) -> str | None:
        for key in keys:
            value = meta.get(key)
            if value:
                return value
        return None

    content.title = first("og:title", "twitter:title") or (parser.title or "").strip() or node.get("headline") or node.get("name")
    content.description = (
        first("og:description", "twitter:description", "description") or node.get("description")
    )
    content.thumbnail_url = first("og:image", "twitter:image") or node.get("thumbnailUrl")
    if isinstance(content.thumbnail_url, list):
        content.thumbnail_url = content.thumbnail_url[0] if content.thumbnail_url else None
    author = first("og:site_name", "article:author")
    node_author = node.get("author")
    if not author and isinstance(node_author, dict):
        author = node_author.get("name")
    content.author = author
    duration = first("og:video:duration")
    if duration and duration.isdigit():
        content.duration_s = float(duration)

    text_parser = _TextParser()
    try:
        text_parser.feed(page[:MAX_HTML_BYTES])
    except Exception as exc:
        logger.debug("Text parse warning: %s", exc)
    text = re.sub(r"\s+", " ", " ".join(text_parser.chunks)).strip()
    if text:
        content.page_text = text[:MAX_TEXT_CHARS]
    return content


async def _extract_oembed(client: httpx.AsyncClient, url: str, platform: str, endpoint: str) -> LinkContent | None:
    from urllib.parse import quote

    data = await _get_json(client, f"{endpoint}?url={quote(url, safe='')}&format=json")
    if not data:
        return None
    return LinkContent(
        url=url,
        platform=platform,
        title=data.get("title"),
        author=data.get("author_name"),
        thumbnail_url=data.get("thumbnail_url"),
    )


async def extract_link(url: str, *, use_cache: bool = True) -> LinkContent:
    """Fetch public metadata for a link. Raises ValueError with a user-facing message."""
    url = url.strip()
    if not url:
        raise ValueError("Hãy dán một đường link video hoặc bài viết.")
    await _assert_public_url(url)

    cached = _cache.get(url)
    if use_cache and cached and time.time() - cached[0] < CACHE_TTL_S:
        return cached[1]

    platform = detect_platform(url)
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        content: LinkContent | None = None
        if platform == "youtube":
            video_id = _youtube_id(url)
            if not video_id:
                raise ValueError("Không nhận diện được ID video YouTube trong link.")
            content = await _extract_oembed(client, url, platform, "https://www.youtube.com/oembed")
            if content is None:
                # oEmbed refused — fall back to scraping the watch page metadata
                content = await _extract_generic(client, url, platform)
            content.video_id = video_id
            captions, lang = await _youtube_captions(client, video_id)
            content.captions = captions
            content.captions_lang = lang
        elif platform == "tiktok":
            content = await _extract_oembed(client, url, platform, "https://www.tiktok.com/oembed")
            if content is None:
                content = await _extract_generic(client, url, platform)
            match = _TT_ID_RE.search(url)
            if match:
                content.video_id = match.group(1)
        elif platform in ("instagram", "facebook", "x"):
            # oEmbed for these networks needs an app token; try, then scrape.
            endpoints = {
                "instagram": "https://graph.facebook.com/v18.0/oembed_post",
                "facebook": "https://graph.facebook.com/v18.0/oembed_post",
                "x": "https://publish.twitter.com/oembed",
            }
            content = await _extract_oembed(client, url, platform, endpoints[platform])
            if content is None:
                content = await _extract_generic(client, url, platform)
        else:
            content = await _extract_generic(client, url, platform)

    if not content.title and not content.description and not content.captions and not content.page_text:
        raise ValueError("Không bóc tách được nội dung từ link này (trang trống hoặc chặn truy cập).")
    _cache[url] = (time.time(), content)
    return content
