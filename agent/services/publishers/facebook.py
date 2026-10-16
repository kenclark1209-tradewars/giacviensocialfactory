"""Facebook Page publisher — Graph API video upload.

Posts to a Facebook **Page** (personal timelines can't be posted via API).
Setup: Meta app with pages_manage_posts (+ pages_read_engagement),
redirect URI = {PUBLISH_REDIRECT_BASE}/api/publish/callback/facebook
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

_GRAPH = "https://graph.facebook.com/v21.0"
_AUTH_URL = "https://www.facebook.com/v21.0/dialog/oauth"
_SCOPES = "pages_manage_posts,pages_read_engagement"


def _redirect_uri() -> str:
    return f"{config.PUBLISH_REDIRECT_BASE}/api/publish/callback/facebook"


class FacebookPublisher(Publisher):
    platform_id = "facebook"

    def __init__(self, scopes: str = _SCOPES):
        self._scopes_value = scopes

    info = PlatformInfo(
        id="facebook",
        name="Facebook",
        description="Đăng video lên Trang (Page) Facebook của bạn.",
        setup_hint=(
            "Tạo app trên developers.facebook.com, thêm quyền pages_manage_posts, "
            "thêm redirect URI trỏ về /api/publish/callback/facebook rồi điền "
            "FACEBOOK_APP_ID / FACEBOOK_APP_SECRET vào env. Lưu ý: đăng lên Page, "
            "không đăng được lên trang cá nhân qua API."
        ),
    )

    def _scopes(self) -> str:
        return self._scopes_value

    def _configured(self) -> bool:
        return bool(config.FACEBOOK_APP_ID and config.FACEBOOK_APP_SECRET)

    async def connect_url(self, state: str) -> str:
        if not self._configured():
            raise RuntimeError("Chưa cấu hình FACEBOOK_APP_ID / FACEBOOK_APP_SECRET.")
        return f"{_AUTH_URL}?{urlencode({'client_id': config.FACEBOOK_APP_ID, 'redirect_uri': _redirect_uri(), 'scope': self._scopes(), 'state': state})}"

    async def _extend_token(self, client: httpx.AsyncClient, short_token: str) -> tuple[str, str | None]:
        resp = await client.get(f"{_GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": config.FACEBOOK_APP_ID,
            "client_secret": config.FACEBOOK_APP_SECRET,
            "fb_exchange_token": short_token,
        })
        if resp.status_code != 200:
            return short_token, None
        data = resp.json()
        exp = (datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 5184000)))).isoformat()
        return data["access_token"], exp

    async def exchange_code(self, code: str) -> PublishAccount:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_GRAPH}/oauth/access_token", params={
                "client_id": config.FACEBOOK_APP_ID,
                "redirect_uri": _redirect_uri(),
                "client_secret": config.FACEBOOK_APP_SECRET,
                "code": code,
            })
            if resp.status_code != 200:
                raise RuntimeError(f"Facebook token exchange thất bại ({resp.status_code}).")
            short_token = resp.json()["access_token"]
            long_token, expires_at = await self._extend_token(client, short_token)
            pages = await client.get(f"{_GRAPH}/me/accounts", params={"access_token": long_token, "limit": 50})
        if pages.status_code != 200:
            raise RuntimeError("Không lấy được danh sách Page. Bạn đã cấp quyền pages_manage_posts chưa?")
        items = pages.json().get("data") or []
        if not items:
            raise RuntimeError("Tài khoản này không quản lý Page nào.")
        page = items[0]
        return PublishAccount(
            platform="facebook",
            account_id=page["id"],
            account_name=page.get("name"),
            access_token=page.get("access_token", long_token),
            expires_at=expires_at,
            scopes=_SCOPES,
            extra={"page_id": page["id"], "user_token": long_token},
        )

    async def publish(self, account: PublishAccount, video_path: Path, options: PublishOptions) -> PublishResult:
        page_id = (account.extra or {}).get("page_id") or account.account_id
        if not page_id:
            return PublishResult(ok=False, error="Thiếu Page ID — hãy kết nối lại Facebook.")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                with open(video_path, "rb") as f:
                    resp = await client.post(
                        f"{_GRAPH}/{page_id}/videos",
                        data={"description": options.caption[:5000], "access_token": account.access_token},
                        files={"source": (video_path.name, f, "video/mp4")},
                        timeout=900,
                    )
                if resp.status_code != 200:
                    return PublishResult(ok=False, error=f"Facebook từ chối upload ({resp.status_code}): {resp.text[:200]}")
                vid = resp.json().get("id")
                return PublishResult(
                    ok=True, external_id=vid,
                    external_url=f"https://www.facebook.com/{page_id}/videos/{vid}",
                )
        except httpx.HTTPError as exc:
            return PublishResult(ok=False, error=f"Lỗi mạng khi đăng Facebook: {exc}")
