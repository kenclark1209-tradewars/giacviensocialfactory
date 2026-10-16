"""Unit tests for social publishers — all HTTP mocked."""
import json
from pathlib import Path

import httpx
import pytest

from agent import config
from agent.services.publishers import PUBLISHERS
from agent.services.publishers.base import PublishAccount, PublishOptions
from agent.services.publishers.youtube import YouTubePublisher
from agent.services.publishers.facebook import FacebookPublisher
from agent.services.publishers.instagram import InstagramPublisher
from agent.services.publishers.tiktok import TikTokPublisher


class FakeResponse:
    def __init__(self, status=200, json_data=None, headers=None, text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        self.headers = headers or {}
        self.text = text or json.dumps(self._json)

    def json(self):
        return self._json


class FakeClient:
    """Drop-in for httpx.AsyncClient driven by a handler(method, url, kwargs)."""

    def __init__(self, handler, *args, **kwargs):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        return self._handler("POST", url, kwargs)

    async def get(self, url, **kwargs):
        return self._handler("GET", url, kwargs)

    async def put(self, url, **kwargs):
        return self._handler("PUT", url, kwargs)


@pytest.fixture
def fake_http(monkeypatch):
    handlers = {}

    def _client(handler_key="default"):
        def make(*args, **kwargs):
            return FakeClient(handlers[handler_key])
        return make

    monkeypatch.setattr(httpx, "AsyncClient", _client())
    return handlers


@pytest.fixture
def video_file(tmp_path):
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00" * 1024)
    return p


@pytest.fixture
def yt_config(monkeypatch):
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_ID", "yt-id")
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_SECRET", "yt-secret")


def _account(platform="youtube"):
    return PublishAccount(platform=platform, account_name="Test", access_token="tok")


# ── registry ──────────────────────────────────────────────

def test_registry_has_four_platforms():
    assert set(PUBLISHERS) == {"youtube", "facebook", "instagram", "tiktok"}


def test_account_expired_logic():
    fresh = PublishAccount(platform="x", access_token="t", expires_at="2999-01-01T00:00:00+00:00")
    assert not fresh.expired()
    old = PublishAccount(platform="x", access_token="t", expires_at="2000-01-01T00:00:00+00:00")
    assert old.expired()
    noexp = PublishAccount(platform="x", access_token="t")
    assert not noexp.expired()


# ── YouTube ───────────────────────────────────────────────

async def test_youtube_connect_url(fake_http, yt_config):
    url = await YouTubePublisher().connect_url("state123")
    assert "accounts.google.com" in url
    assert "youtube.upload" in url
    assert "state123" in url


async def test_youtube_connect_url_requires_config(monkeypatch):
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_ID", "")
    monkeypatch.setattr(config, "YOUTUBE_CLIENT_SECRET", "")
    with pytest.raises(RuntimeError):
        await YouTubePublisher().connect_url("s")


async def test_youtube_publish_ok(fake_http, yt_config, video_file):
    def handler(method, url, kwargs):
        if method == "POST" and "upload/youtube" in url:
            return FakeResponse(200, headers={"Location": "https://session.example/u"})
        if method == "PUT":
            assert kwargs["headers"]["Content-Type"] == "video/mp4"
            return FakeResponse(200, {"id": "vid123"})
        raise AssertionError(f"unexpected {method} {url}")

    fake_http["default"] = handler
    res = await YouTubePublisher().publish(_account(), video_file, PublishOptions(caption="hello"))
    assert res.ok and res.external_id == "vid123"
    assert res.external_url == "https://www.youtube.com/watch?v=vid123"


async def test_youtube_publish_init_rejected(fake_http, yt_config, video_file):
    fake_http["default"] = lambda m, u, k: FakeResponse(400, text="bad")
    res = await YouTubePublisher().publish(_account(), video_file, PublishOptions())
    assert not res.ok and "400" in res.error


async def test_youtube_refresh(fake_http, yt_config):
    fake_http["default"] = lambda m, u, k: FakeResponse(200, {"access_token": "new-tok", "expires_in": 3600})
    acc = PublishAccount(platform="youtube", access_token="old", refresh_token="rt")
    out = await YouTubePublisher().refresh(acc)
    assert out is not None and out.access_token == "new-tok"


# ── Facebook ──────────────────────────────────────────────

async def test_facebook_connect_url(monkeypatch):
    monkeypatch.setattr(config, "FACEBOOK_APP_ID", "fb-id")
    monkeypatch.setattr(config, "FACEBOOK_APP_SECRET", "fb-secret")
    url = await FacebookPublisher().connect_url("s")
    assert "facebook.com" in url and "dialog/oauth" in url


async def test_facebook_publish_ok(fake_http, video_file):
    def handler(method, url, kwargs):
        assert method == "POST" and url.endswith("/page1/videos")
        return FakeResponse(200, {"id": "fbvid"})
    fake_http["default"] = handler
    acc = PublishAccount(platform="facebook", access_token="tok", extra={"page_id": "page1"})
    res = await FacebookPublisher().publish(acc, video_file, PublishOptions(caption="hi"))
    assert res.ok and res.external_id == "fbvid"
    assert "facebook.com" in res.external_url


async def test_facebook_publish_no_page(video_file):
    acc = PublishAccount(platform="facebook", access_token="tok")
    res = await FacebookPublisher().publish(acc, video_file, PublishOptions())
    assert not res.ok


# ── Instagram ─────────────────────────────────────────────

async def test_instagram_requires_public_url(video_file):
    acc = PublishAccount(platform="instagram", access_token="tok", extra={"ig_user_id": "ig1"})
    res = await InstagramPublisher().publish(acc, video_file, PublishOptions(caption="x"))
    assert not res.ok and "công khai" in res.error


async def test_instagram_publish_ok(fake_http, video_file):
    calls = []

    def handler(method, url, kwargs):
        calls.append((method, url))
        if url.endswith("/ig1/media"):
            return FakeResponse(200, {"id": "cont1"})
        if url.endswith("/cont1"):
            return FakeResponse(200, {"status_code": "FINISHED"})
        if url.endswith("/ig1/media_publish"):
            return FakeResponse(200, {"id": "media9"})
        if url.endswith("/media9"):
            return FakeResponse(200, {"permalink": "https://instagram.com/p/abc"})
        raise AssertionError(f"unexpected {method} {url}")

    fake_http["default"] = handler
    acc = PublishAccount(platform="instagram", access_token="tok", extra={"ig_user_id": "ig1"})
    res = await InstagramPublisher().publish(
        acc, video_file, PublishOptions(caption="reel", public_url="https://cdn.example/v.mp4"))
    assert res.ok and res.external_url == "https://instagram.com/p/abc"


# ── TikTok ────────────────────────────────────────────────

async def test_tiktok_connect_url(monkeypatch):
    monkeypatch.setattr(config, "TIKTOK_CLIENT_KEY", "tt-key")
    monkeypatch.setattr(config, "TIKTOK_CLIENT_SECRET", "tt-secret")
    url = await TikTokPublisher().connect_url("s")
    assert "tiktok.com/v2/auth/authorize" in url


async def test_tiktok_publish_ok(fake_http, video_file):
    def handler(method, url, kwargs):
        if url.endswith("/post/publish/video/init/"):
            return FakeResponse(200, {"data": {"publish_id": "pub1", "upload_url": "https://up.example/x"}, "error": {"code": "ok"}})
        if method == "PUT":
            assert kwargs["headers"]["Content-Range"].startswith("bytes 0-")
            return FakeResponse(201)
        if url.endswith("/post/publish/status/fetch/"):
            return FakeResponse(200, {"data": {"status": "PUBLISH_COMPLETE"}, "error": {"code": "ok"}})
        raise AssertionError(f"unexpected {method} {url}")

    fake_http["default"] = handler
    res = await TikTokPublisher().publish(_account("tiktok"), video_file, PublishOptions(caption="tt #fyp"))
    assert res.ok and res.external_id == "pub1"


async def test_tiktok_publish_init_rejected(fake_http, video_file):
    fake_http["default"] = lambda m, u, k: FakeResponse(200, {"data": {}, "error": {"code": "spam", "message": "nope"}})
    res = await TikTokPublisher().publish(_account("tiktok"), video_file, PublishOptions())
    assert not res.ok
