"""TikTok publisher — Content Posting API v2 (direct post, FILE_UPLOAD).

Setup: TikTok developer app with the Content Posting API scope approved
(audit). Redirect URI = {PUBLISH_REDIRECT_BASE}/api/publish/callback/tiktok
Flow: init -> PUT chunks to upload_url -> poll status/fetch until PUBLISH_COMPLETE.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from agent import config
from .base import PlatformInfo, PublishAccount, PublishOptions, PublishResult, Publisher

logger = logging.getLogger(__name__)

_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
_API = "https://open.tiktokapis.com/v2"
_SCOPES = "user.info.basic,video.upload,video.publish"
_CHUNK = 10 * 1024 * 1024  # 10 MB, inside TikTok's 5–64 MB window


def _redirect_uri() -> str:
    return f"{config.PUBLISH_REDIRECT_BASE}/api/publish/callback/tiktok"


class TikTokPublisher(Publisher):
    platform_id = "tiktok"
    info = PlatformInfo(
        id="tiktok",
        name="TikTok",
        description="Đăng video trực tiếp lên TikTok của bạn.",
        setup_hint=(
            "Tạo app trên developers.tiktok.com, xin duyệt quyền Content Posting API "
            "(mất vài ngày), thêm redirect URI trỏ về /api/publish/callback/tiktok rồi "
            "điền TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET vào env."
        ),
    )

    def _configured(self) -> bool:
        return bool(config.TIKTOK_CLIENT_KEY and config.TIKTOK_CLIENT_SECRET)

    async def connect_url(self, state: str) -> str:
        if not self._configured():
            raise RuntimeError("Chưa cấu hình TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET.")
        return f"{_AUTH_URL}?{urlencode({'client_key': config.TIKTOK_CLIENT_KEY, 'scope': _SCOPES, 'response_type': 'code', 'redirect_uri': _redirect_uri(), 'state': state})}"

    async def _token_request(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(_TOKEN_URL, json=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"TikTok token request thất bại ({resp.status_code}).")
        data = resp.json()
        if data.get("error", {}).get("code") not in (None, "ok"):
            raise RuntimeError(f"TikTok token lỗi: {data['error'].get('message')}")
        return data["data"]

    async def exchange_code(self, code: str) -> PublishAccount:
        tok = await self._token_request({
            "client_key": config.TIKTOK_CLIENT_KEY,
            "client_secret": config.TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        })
        # Fetch display name for the connected account
        name = None
        async with httpx.AsyncClient(timeout=30) as client:
            me = await client.post(
                f"{_API}/user/info/",
                headers={"Authorization": f"Bearer {tok['access_token']}"},
                json={"fields": ["display_name"]},
            )
        if me.status_code == 200:
            user = (me.json().get("data") or {}).get("user") or {}
            name = user.get("display_name")
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 86400)))).isoformat()
        return PublishAccount(
            platform="tiktok",
            account_name=name,
            access_token=tok["access_token"],
            refresh_token=tok.get("refresh_token"),
            expires_at=expires_at,
            scopes=tok.get("scope", _SCOPES),
            extra={"open_id": tok.get("open_id")},
        )

    async def refresh(self, account: PublishAccount) -> PublishAccount | None:
        if not account.refresh_token:
            return None
        try:
            tok = await self._token_request({
                "client_key": config.TIKTOK_CLIENT_KEY,
                "client_secret": config.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
            })
        except RuntimeError as exc:
            logger.warning("TikTok refresh failed: %s", exc)
            return None
        account.access_token = tok["access_token"]
        account.refresh_token = tok.get("refresh_token", account.refresh_token)
        account.expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(tok.get("expires_in", 86400)))).isoformat()
        return account

    async def publish(self, account: PublishAccount, video_path: Path, options: PublishOptions) -> PublishResult:
        size = video_path.stat().st_size
        chunk = size if size < 5 * 1024 * 1024 else _CHUNK
        total_chunks = 1 if size < 5 * 1024 * 1024 else math.ceil(size / chunk)
        headers = {"Authorization": f"Bearer {account.access_token}", "Content-Type": "application/json; charset=UTF-8"}
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                init = await client.post(f"{_API}/post/publish/video/init/", headers=headers, json={
                    "post_info": {
                        "title": options.caption[:2200],
                        "privacy_level": options.tiktok_privacy,
                        "disable_comment": False,
                        "disable_duet": False,
                        "disable_stitch": False,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk,
                        "total_chunk_count": total_chunks,
                    },
                })
                data = init.json().get("data") or {}
                err = init.json().get("error") or {}
                if init.status_code != 200 or err.get("code") not in (None, "ok") or "upload_url" not in data:
                    return PublishResult(ok=False, error=f"TikTok từ chối khởi tạo upload: {err.get('message') or init.text[:200]}")
                publish_id = data["publish_id"]
                upload_url = data["upload_url"]
                with open(video_path, "rb") as f:
                    for i in range(total_chunks):
                        start = i * chunk
                        blob = f.read(chunk)
                        end = start + len(blob) - 1
                        put = await client.put(upload_url, content=blob, headers={
                            "Content-Type": "video/mp4",
                            "Content-Range": f"bytes {start}-{end}/{size}",
                        }, timeout=900)
                        if i < total_chunks - 1 and put.status_code != 206:
                            return PublishResult(ok=False, error=f"TikTok upload chunk {i+1} thất bại ({put.status_code}).")
                        if i == total_chunks - 1 and put.status_code != 201:
                            return PublishResult(ok=False, error=f"TikTok upload chunk cuối thất bại ({put.status_code}).")
                # Poll processing status
                for _ in range(60):
                    st = await client.post(f"{_API}/post/publish/status/fetch/", headers=headers, json={"publish_id": publish_id})
                    sdata = (st.json().get("data") or {})
                    status = sdata.get("status")
                    if status == "PUBLISH_COMPLETE":
                        return PublishResult(ok=True, external_id=publish_id)
                    if status in ("FAILED",):
                        return PublishResult(ok=False, error=f"TikTok xử lý video thất bại ({sdata.get('fail_reason') or status}).")
                    await asyncio.sleep(10)
                return PublishResult(ok=False, error="TikTok xử lý quá lâu, hãy kiểm tra lại trên app TikTok.", external_id=publish_id)
        except httpx.HTTPError as exc:
            return PublishResult(ok=False, error=f"Lỗi mạng khi đăng TikTok: {exc}")
