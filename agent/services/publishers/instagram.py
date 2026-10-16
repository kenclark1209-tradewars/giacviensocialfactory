"""Instagram Reels publisher — Instagram Graph API.

Requires a Business/Creator account linked to the Facebook Page used at
connect time. Meta pulls the video from a PUBLIC URL, so the user must
provide one (the backend is usually localhost).
Setup: same Meta app as Facebook + instagram_basic, instagram_content_publish.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from .base import PlatformInfo, PublishAccount, PublishOptions, PublishResult, Publisher
from .facebook import _GRAPH, _SCOPES as _FB_SCOPES, FacebookPublisher

logger = logging.getLogger(__name__)

_IG_SCOPES = "instagram_basic,instagram_content_publish"


class InstagramPublisher(Publisher):
    platform_id = "instagram"
    info = PlatformInfo(
        id="instagram",
        name="Instagram",
        description="Đăng Reels lên tài khoản Business/Creator đã liên kết với Page.",
        needs_public_url=True,
        setup_hint=(
            "Dùng chung app Facebook ở trên, thêm quyền instagram_basic và "
            "instagram_content_publish. Tài khoản Instagram phải là Business/Creator "
            "và đã liên kết với Page. Meta tải video từ URL công khai nên bạn cần "
            "dán link công khai của file video (ví dụ đã up lên Drive/S3)."
        ),
    )

    def _fb(self) -> FacebookPublisher:
        # Reuse the Facebook OAuth; IG permissions are requested together.
        return FacebookPublisher(scopes=f"{_FB_SCOPES},{_IG_SCOPES}")

    async def connect_url(self, state: str) -> str:
        return await self._fb().connect_url(state)

    async def _ig_user_id(self, account: PublishAccount) -> str | None:
        page_id = (account.extra or {}).get("page_id") or account.account_id
        user_token = (account.extra or {}).get("user_token") or account.access_token
        if not page_id:
            return None
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_GRAPH}/{page_id}", params={
                "fields": "instagram_business_account", "access_token": user_token,
            })
        if resp.status_code != 200:
            return None
        ig = resp.json().get("instagram_business_account") or {}
        return ig.get("id")

    async def exchange_code(self, code: str) -> PublishAccount:
        fb_account = await self._fb().exchange_code(code)
        ig_id = await self._ig_user_id(fb_account)
        if not ig_id:
            raise RuntimeError("Không tìm thấy tài khoản Instagram Business/Creator liên kết với Page.")
        async with httpx.AsyncClient(timeout=30) as client:
            me = await client.get(f"{_GRAPH}/{ig_id}", params={
                "fields": "username", "access_token": fb_account.access_token,
            })
        username = me.json().get("username") if me.status_code == 200 else None
        fb_account.platform = "instagram"
        fb_account.account_id = ig_id
        fb_account.account_name = f"@{username}" if username else ig_id
        fb_account.extra = {**(fb_account.extra or {}), "ig_user_id": ig_id}
        return fb_account

    async def publish(self, account: PublishAccount, video_path: Path, options: PublishOptions) -> PublishResult:
        ig_id = (account.extra or {}).get("ig_user_id") or account.account_id
        if not ig_id:
            return PublishResult(ok=False, error="Thiếu Instagram user ID — hãy kết nối lại.")
        if not options.public_url:
            return PublishResult(ok=False, error="Instagram cần URL công khai của video. Hãy dán link công khai vào ô bên dưới.")
        token = account.access_token
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                cont = await client.post(f"{_GRAPH}/{ig_id}/media", data={
                    "media_type": "REELS",
                    "video_url": options.public_url,
                    "caption": options.caption[:2200],
                    "share_to_feed": "true",
                    "access_token": token,
                })
                if cont.status_code != 200:
                    return PublishResult(ok=False, error=f"Instagram từ chối tạo media ({cont.status_code}): {cont.text[:200]}")
                creation_id = cont.json().get("id")
                # Wait for Meta to finish processing the container
                for _ in range(30):
                    st = await client.get(f"{_GRAPH}/{creation_id}", params={"fields": "status_code", "access_token": token})
                    code = (st.json() or {}).get("status_code")
                    if code == "FINISHED":
                        break
                    if code in ("ERROR", "EXPIRED"):
                        return PublishResult(ok=False, error=f"Instagram xử lý video thất bại ({code}).")
                    await asyncio.sleep(10)
                else:
                    return PublishResult(ok=False, error="Instagram xử lý quá lâu, hãy thử lại sau.")
                pub = await client.post(f"{_GRAPH}/{ig_id}/media_publish", data={
                    "creation_id": creation_id, "access_token": token,
                })
                if pub.status_code != 200:
                    return PublishResult(ok=False, error=f"Instagram publish thất bại ({pub.status_code}): {pub.text[:200]}")
                media_id = pub.json().get("id")
                link = await client.get(f"{_GRAPH}/{media_id}", params={"fields": "permalink", "access_token": token})
                permalink = link.json().get("permalink") if link.status_code == 200 else None
                return PublishResult(ok=True, external_id=media_id, external_url=permalink)
        except httpx.HTTPError as exc:
            return PublishResult(ok=False, error=f"Lỗi mạng khi đăng Instagram: {exc}")
