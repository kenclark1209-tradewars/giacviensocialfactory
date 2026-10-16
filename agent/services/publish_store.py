"""SQLite persistence for publish accounts and jobs."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from agent.db.schema import get_db
from agent.services.publishers.base import PublishAccount


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _account_from_row(row) -> PublishAccount:
    extra = {}
    if row["extra"]:
        try:
            extra = json.loads(row["extra"])
        except (ValueError, TypeError):
            extra = {}
    return PublishAccount(
        platform=row["platform"],
        account_id=row["account_id"],
        account_name=row["account_name"],
        access_token=row["access_token"],
        refresh_token=row["refresh_token"],
        expires_at=row["expires_at"],
        scopes=row["scopes"],
        extra=extra,
    )


async def save_account(account: PublishAccount) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO publish_account
           (platform, account_id, account_name, access_token, refresh_token, expires_at, scopes, extra, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(platform) DO UPDATE SET
             account_id=excluded.account_id, account_name=excluded.account_name,
             access_token=excluded.access_token, refresh_token=excluded.refresh_token,
             expires_at=excluded.expires_at, scopes=excluded.scopes, extra=excluded.extra,
             updated_at=excluded.updated_at""",
        (account.platform, account.account_id, account.account_name, account.access_token,
         account.refresh_token, account.expires_at, account.scopes,
         json.dumps(account.extra or {}), _now()),
    )
    await db.commit()


async def get_account(platform: str) -> PublishAccount | None:
    db = await get_db()
    cur = await db.execute("SELECT * FROM publish_account WHERE platform = ?", (platform,))
    row = await cur.fetchone()
    return _account_from_row(row) if row else None


async def delete_account(platform: str) -> None:
    db = await get_db()
    await db.execute("DELETE FROM publish_account WHERE platform = ?", (platform,))
    await db.commit()


async def create_job(video_id: str, platform: str, caption: str) -> dict:
    job_id = f"pub_{uuid.uuid4().hex[:12]}"
    db = await get_db()
    await db.execute(
        "INSERT INTO publish_job (id, video_id, platform, status, caption) VALUES (?, ?, ?, 'QUEUED', ?)",
        (job_id, video_id, platform, caption),
    )
    await db.commit()
    return {"id": job_id, "video_id": video_id, "platform": platform, "status": "QUEUED",
            "external_id": None, "external_url": None, "caption": caption, "error": None}


async def update_job(job_id: str, **fields) -> None:
    allowed = {"status", "external_id", "external_url", "error"}
    sets = [f"{k} = ?" for k in fields if k in allowed]
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
    db = await get_db()
    await db.execute(
        f"UPDATE publish_job SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
        (*vals, _now(), job_id),
    )
    await db.commit()


async def list_jobs(video_id: str | None = None, limit: int = 50) -> list[dict]:
    db = await get_db()
    if video_id:
        cur = await db.execute(
            "SELECT * FROM publish_job WHERE video_id = ? ORDER BY created_at DESC LIMIT ?", (video_id, limit))
    else:
        cur = await db.execute("SELECT * FROM publish_job ORDER BY created_at DESC LIMIT ?", (limit,))
    return [dict(r) for r in await cur.fetchall()]
