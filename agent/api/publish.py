"""Social publish API — connect platform accounts and post finished videos."""
from __future__ import annotations

import logging
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from agent import config
from agent.db import crud
from agent.services import publish_store
from agent.services.publishers import PUBLISHERS
from agent.services.publishers.base import PublishOptions
from agent.services.video_assembly import assembled_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/publish", tags=["publish"])

# OAuth state tokens (single-process; 10-minute TTL)
_states: dict[str, tuple[str, float]] = {}


async def _resolve_video_file(video_id: str) -> Path:
    video = await crud.get_video(video_id)
    if not video:
        raise HTTPException(404, "Không tìm thấy video.")
    path = assembled_path(video_id)
    if not path.is_file():
        from agent.services.imported_video import source_path
        path = source_path(video_id)
    if not path.is_file():
        raise HTTPException(400, "Video chưa có file MP4 để đăng.")
    return path


class PublishRequest(BaseModel):
    video_id: str
    platforms: list[str] = Field(min_length=1)
    caption: str = ""
    title: str = ""
    youtube_privacy: str = "unlisted"
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"
    public_url: str | None = None


@router.get("/platforms")
async def list_platforms() -> dict[str, Any]:
    items = []
    for pid, pub in PUBLISHERS.items():
        account = await publish_store.get_account(pid)
        try:
            await pub.connect_url("probe")
            app_ready = True
            app_error = None
        except RuntimeError as exc:
            app_ready = False
            app_error = str(exc)
        items.append({
            "id": pid,
            "name": pub.info.name,
            "description": pub.info.description,
            "needs_public_url": pub.info.needs_public_url,
            "setup_hint": pub.info.setup_hint,
            "app_ready": app_ready,
            "app_error": app_error,
            "connected": account is not None,
            "account_name": account.account_name if account else None,
        })
    return {"platforms": items}


@router.get("/connect/{platform}")
async def connect(platform: str) -> dict[str, str]:
    pub = PUBLISHERS.get(platform)
    if not pub:
        raise HTTPException(404, "Nền tảng không hỗ trợ.")
    state = secrets.token_urlsafe(16)
    _states[state] = (platform, time.time())
    try:
        url = await pub.connect_url(state)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return {"url": url}


@router.get("/callback/{platform}", response_class=HTMLResponse)
async def callback(platform: str, code: str | None = None, state: str | None = None, error: str | None = None):
    pub = PUBLISHERS.get(platform)
    if error:
        return HTMLResponse(f"<h3>Kết nối {platform} thất bại</h3><p>{error}</p>", status_code=400)
    if not pub or not code or not state or state not in _states or _states[state][0] != platform:
        return HTMLResponse("<h3>Phiên kết nối không hợp lệ hoặc đã hết hạn.</h3>", status_code=400)
    if time.time() - _states[state][1] > 600:
        del _states[state]
        return HTMLResponse("<h3>Phiên kết nối đã hết hạn, hãy thử lại.</h3>", status_code=400)
    del _states[state]
    try:
        account = await pub.exchange_code(code)
    except RuntimeError as exc:
        return HTMLResponse(f"<h3>Kết nối thất bại</h3><p>{exc}</p>", status_code=400)
    await publish_store.save_account(account)
    name = account.account_name or platform
    return HTMLResponse(
        f"<h3>Đã kết nối {pub.info.name} ({name}) ✓</h3>"
        "<p>Bạn có thể đóng tab này và quay lại dashboard để đăng video.</p>"
    )


@router.delete("/accounts/{platform}")
async def disconnect(platform: str) -> dict[str, bool]:
    await publish_store.delete_account(platform)
    return {"ok": True}


@router.get("/jobs")
async def jobs(video_id: str | None = None) -> dict[str, Any]:
    return {"jobs": await publish_store.list_jobs(video_id)}


async def _run_job(job_id: str, platform: str, video_path: Path, options: PublishOptions) -> None:
    pub = PUBLISHERS[platform]
    try:
        account = await publish_store.get_account(platform)
        if not account:
            raise RuntimeError("Tài khoản chưa được kết nối.")
        if account.expired():
            refreshed = await pub.refresh(account)
            if refreshed:
                await publish_store.save_account(refreshed)
                account = refreshed
            else:
                raise RuntimeError("Token đã hết hạn và không tự gia hạn được — hãy kết nối lại.")
        await publish_store.update_job(job_id, status="UPLOADING")
        result = await pub.publish(account, video_path, options)
        if result.ok:
            await publish_store.update_job(
                job_id, status="DONE", external_id=result.external_id,
                external_url=result.external_url)
        else:
            await publish_store.update_job(job_id, status="FAILED", error=result.error,
                                           external_id=result.external_id)
    except Exception as exc:  # never let a background task die silently
        logger.exception("publish job %s failed", job_id)
        await publish_store.update_job(job_id, status="FAILED", error=str(exc)[:500])


@router.post("")
async def publish(body: PublishRequest, background: BackgroundTasks) -> dict[str, Any]:
    unknown = [p for p in body.platforms if p not in PUBLISHERS]
    if unknown:
        raise HTTPException(400, f"Nền tảng không hỗ trợ: {', '.join(unknown)}")
    video_path = await _resolve_video_file(body.video_id)
    options = PublishOptions(
        caption=body.caption, title=body.title,
        youtube_privacy=body.youtube_privacy, tiktok_privacy=body.tiktok_privacy,
        public_url=body.public_url,
    )
    jobs = []
    for platform in body.platforms:
        account = await publish_store.get_account(platform)
        if not account:
            raise HTTPException(400, f"Chưa kết nối {PUBLISHERS[platform].info.name}. Hãy kết nối trước.")
        job = await publish_store.create_job(body.video_id, platform, body.caption)
        background.add_task(_run_job, job["id"], platform, video_path, options)
        jobs.append(job)
    return {"jobs": jobs}
