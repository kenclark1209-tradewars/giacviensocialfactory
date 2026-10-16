"""YouTube publisher — YouTube Data API v3, resumable upload.

Setup: Google Cloud project with "YouTube Data API v3" enabled, OAuth 2.0
Client ID (Desktop/Web), redirect URI = {PUBLISH_REDIRECT_BASE}/api/publish/callback/youtube
Scope: https://www.googleapis.com/auth/youtube.upload
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from agent import config
from .base import PlatformInfo, PublishAccount, PublishOptions, PublishResult, Publisher

logger = logging.getLogger(__name__)

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_INIT = "https://www.googleapis.com/upload/youtube/v3/videos"
_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def _redirect_uri() -> str:
    return f"{config.PUBLISH_REDIRECT_BASE}/api/publish/callback/youtube"


class YouTubePublisher(Publisher):
    platform_id = "youtube"
    info = PlatformInfo(
        id="youtube",
        name="YouTube",
        description="Đăng video lên kênh YouTube của bạn (mặc định để Unlisted).",
        setup_hint=(
            "Tạo project trên Google Cloud, bật YouTube Data API v3, tạo OAuth Client ID, "
            "thêm redirect URI trỏ về /api/publish/callback/youtube rồi điền "
            "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET vào env."
        ),
    )

    def _configured(self) -> bool:
        return bool(config.YOUTUBE_CLIENT_ID and config.YOUTUBE_CLIENT_SECRET)

    async def connect_url(self, state: str) -> str:
        if not self._configured():
            raise RuntimeError("Chưa cấu hình YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET.")
        params = {
            "client_id": config.YOUTUBE_CLIENT_ID,
            "redirect_uri": _redirect_uri(),
            "response_type": "code",
            "scope": _SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> PublishAccount:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN_URL, data={
                "code": code,
                "client_id": config.YOUTUBE_CLIENT_ID,
                "client_secret": config.YOUTUBE_CLIENT_SECRET,
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            })
        if resp.status_code != 200:
            raise RuntimeError(f"YouTube token exchange thất bại ({resp.status_code}).")
        tok = resp.json()
        # Identify the channel for display
        account_name = None
        async with httpx.AsyncClient(timeout=30) as client:
            ch = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {tok['access_token']}"},
            )
        if ch.status_code == 200:
            items = ch.json().get("items") or []
            if items:
                account_name = items[0]["snippet"].get("title")
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))).isoformat()
        return PublishAccount(
            platform="youtube",
            account_name=account_name,
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            expires_at=expires_at,
            scopes=_SCOPE,
        )

    async def refresh(self, account: PublishAccount) -> PublishAccount | None:
        if not account.refresh_token:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
                "client_id": config.YOUTUBE_CLIENT_ID,
                "client_secret": config.YOUTUBE_CLIENT_SECRET,
            })
        if resp.status_code != 200:
            logger.warning("YouTube refresh failed: %s", resp.status_code)
            return None
        tok = resp.json()
        account.access_token = tok["access_token"]
        account.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 3600)))).isoformat()
        return account

    async def publish(self, account: PublishAccount, video_path: Path, options: PublishOptions) -> PublishResult:
        size = video_path.stat().st_size
        title = options.title or (options.caption.splitlines()[0][:100] if options.caption else video_path.stem)
        metadata = {
            "snippet": {
                "title": title[:100],
                "description": options.caption[:5000],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": options.youtube_privacy if options.youtube_privacy in ("public", "unlisted", "private") else "unlisted",
                "selfDeclaredMadeForKids": False,
            },
        }
        headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                init = await client.post(
                    _UPLOAD_INIT,
                    params={"uploadType": "resumable", "part": "snippet,status"},
                    headers=headers,
                    json=metadata,
                )
                if init.status_code not in (200, 201):
                    return PublishResult(ok=False, error=f"YouTube từ chối khởi tạo upload ({init.status_code}): {init.text[:200]}")
                session_uri = init.headers.get("Location")
                if not session_uri:
                    return PublishResult(ok=False, error="YouTube không trả về upload session.")
                with open(video_path, "rb") as f:
                    put = await client.put(
                        session_uri,
                        content=f,
                        headers={"Content-Length": str(size), "Content-Type": "video/mp4"},
                        timeout=600,
                    )
                if put.status_code not in (200, 201):
                    return PublishResult(ok=False, error=f"YouTube upload thất bại ({put.status_code}): {put.text[:200]}")
                vid = put.json().get("id")
                return PublishResult(ok=True, external_id=vid, external_url=f"https://www.youtube.com/watch?v={vid}")
        except httpx.HTTPError as exc:
            return PublishResult(ok=False, error=f"Lỗi mạng khi đăng YouTube: {exc}")
