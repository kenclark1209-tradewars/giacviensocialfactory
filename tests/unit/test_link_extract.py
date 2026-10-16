"""Unit tests for agent/services/link_extract.py.

All network access is stubbed: _get_json / _get_text are monkeypatched, and
_assert_public_url is bypassed where DNS would be needed.
"""
import pytest

from agent.services import link_extract
from agent.services.link_extract import (
    LinkContent,
    _parse_caption_tracks,
    _parse_transcript,
    _pick_caption_lang,
    detect_platform,
    extract_link,
)


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube"),
    ("https://www.tiktok.com/@user/video/1234567890123456789", "tiktok"),
    ("https://www.instagram.com/reel/ABC123/", "instagram"),
    ("https://www.facebook.com/watch/?v=123", "facebook"),
    ("https://x.com/user/status/123", "x"),
    ("https://example.com/article", "web"),
])
def test_detect_platform(url, expected):
    assert detect_platform(url) == expected


def test_youtube_id_extraction():
    assert link_extract._youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert link_extract._youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert link_extract._youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert link_extract._youtube_id("https://www.youtube.com/watch") is None


def test_caption_track_parsing_and_lang_pick():
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <transcript_list>
      <track id="0" name="" lang_code="en" kind=""/>
      <track id="1" name="" lang_code="vi" kind=""/>
    </transcript_list>"""
    tracks = _parse_caption_tracks(xml)
    assert [t["lang_code"] for t in tracks] == ["en", "vi"]
    # Vietnamese is preferred over English.
    assert _pick_caption_lang(tracks) == "vi"
    assert _pick_caption_lang([]) is None


def test_transcript_parsing_unescapes_entities():
    xml = """<?xml version="1.0" encoding="utf-8" ?>
    <transcript>
      <text start="0" dur="2">Hello &amp; welcome</text>
      <text start="2" dur="2">to the <b>show</b></text>
    </transcript>"""
    assert _parse_transcript(xml) == "Hello & welcome to the show"


def test_transcript_parsing_bad_xml_returns_none():
    assert _parse_transcript("not xml at all <") is None


async def _no_network_guard(monkeypatch):
    async def _ok(url: str) -> str:
        return url
    monkeypatch.setattr(link_extract, "_assert_public_url", _ok)
    # Ambient proxy env vars (e.g. sandbox egress config) must not leak into tests.
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        monkeypatch.delenv(var, raising=False)


async def test_extract_youtube_uses_oembed_and_captions(monkeypatch):
    await _no_network_guard(monkeypatch)

    async def fake_json(client, url):
        assert "youtube.com/oembed" in url
        return {"title": "Test video", "author_name": "Tester", "thumbnail_url": "https://i.ytimg.com/vi/x/hq.jpg"}

    async def fake_text(client, url, max_bytes=0):
        if "type=list" in url:
            return ('<?xml version="1.0"?><transcript_list>'
                    '<track lang_code="vi" kind=""/></transcript_list>')
        if "timedtext?lang=vi" in url:
            return ('<?xml version="1.0"?><transcript>'
                    '<text start="0" dur="1">Xin chào</text></transcript>')
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(link_extract, "_get_json", fake_json)
    monkeypatch.setattr(link_extract, "_get_text", fake_text)

    content = await extract_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ", use_cache=False)
    assert content.platform == "youtube"
    assert content.video_id == "dQw4w9WgXcQ"
    assert content.title == "Test video"
    assert content.author == "Tester"
    assert content.captions == "Xin chào"
    assert content.captions_lang == "vi"


async def test_extract_generic_parses_opengraph(monkeypatch):
    await _no_network_guard(monkeypatch)

    page = """<html><head>
      <title>Fallback title</title>
      <meta property="og:title" content="OG Title"/>
      <meta property="og:description" content="OG Description"/>
      <meta property="og:image" content="https://example.com/img.jpg"/>
      <meta property="og:site_name" content="Example"/>
      </head><body><p>Hello world article text.</p></body></html>"""

    async def fake_text(client, url, max_bytes=0):
        return page

    monkeypatch.setattr(link_extract, "_get_text", fake_text)

    content = await extract_link("https://example.com/article", use_cache=False)
    assert content.platform == "web"
    assert content.title == "OG Title"
    assert content.description == "OG Description"
    assert content.thumbnail_url == "https://example.com/img.jpg"
    assert content.author == "Example"
    assert "Hello world article text." in (content.page_text or "")


async def test_extract_empty_url_raises(monkeypatch):
    await _no_network_guard(monkeypatch)
    with pytest.raises(ValueError):
        await extract_link("   ", use_cache=False)


async def test_extract_nothing_found_raises(monkeypatch):
    await _no_network_guard(monkeypatch)

    async def fake_json(client, url):
        return None

    async def fake_text(client, url, max_bytes=0):
        return "<html><head></head><body></body></html>"

    monkeypatch.setattr(link_extract, "_get_json", fake_json)
    monkeypatch.setattr(link_extract, "_get_text", fake_text)
    with pytest.raises(ValueError, match="Không bóc tách được"):
        await extract_link("https://www.tiktok.com/@u/video/1234567890123456789", use_cache=False)


async def test_extract_uses_cache(monkeypatch):
    await _no_network_guard(monkeypatch)
    calls = {"n": 0}

    async def fake_text(client, url, max_bytes=0):
        calls["n"] += 1
        return '<html><head><meta property="og:title" content="Cached"/></head><body></body></html>'

    monkeypatch.setattr(link_extract, "_get_text", fake_text)
    url = "https://example.com/cached-article"
    first = await extract_link(url, use_cache=True)
    second = await extract_link(url, use_cache=True)
    assert first.title == "Cached"
    assert second.title == "Cached"
    assert calls["n"] == 1
    link_extract._cache.pop(url, None)


def test_link_content_to_dict_roundtrip():
    content = LinkContent(url="https://example.com", platform="web", title="T")
    data = content.to_dict()
    assert data["url"] == "https://example.com"
    assert data["platform"] == "web"
    assert data["title"] == "T"


async def test_resolve_final_url_follows_redirects(monkeypatch):
    class FakeResp:
        status_code = 200
        url = "https://www.tiktok.com/@user/video/1234567890123456789"

    class FakeClient:
        async def head(self, url, **kwargs):
            assert "vt.tiktok.com" in url
            return FakeResp()

    resolved = await link_extract._resolve_final_url(FakeClient(), "https://vt.tiktok.com/ZSgFSY5Un/")
    assert resolved == "https://www.tiktok.com/@user/video/1234567890123456789"


async def test_resolve_final_url_falls_back_on_error(monkeypatch):
    import httpx

    class FakeClient:
        async def head(self, url, **kwargs):
            raise httpx.ConnectError("nope")

    url = "https://vt.tiktok.com/ZSgFSY5Un/"
    assert await link_extract._resolve_final_url(FakeClient(), url) == url


async def test_extract_tiktok_short_link_resolves_canonical(monkeypatch):
    await _no_network_guard(monkeypatch)
    canonical = "https://www.tiktok.com/@user/video/1234567890123456789"

    async def fake_resolve(client, url):
        return canonical

    async def fake_json(client, url):
        assert "tiktok.com/oembed" in url and "vt.tiktok.com" not in url
        return {"title": "T", "author_name": "A", "thumbnail_url": "https://x/y.jpg"}

    monkeypatch.setattr(link_extract, "_resolve_final_url", fake_resolve)
    monkeypatch.setattr(link_extract, "_get_json", fake_json)

    content = await extract_link("https://vt.tiktok.com/ZSgFSY5Un/", use_cache=False)
    assert content.video_id == "1234567890123456789"
    assert content.url == canonical
    assert content.title == "T"
