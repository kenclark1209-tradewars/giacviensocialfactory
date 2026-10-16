"""Base classes for social publishers.

Each platform implements :class:`Publisher`:

- ``connect_url(state)`` — OAuth authorize URL the user opens in a browser.
- ``exchange_code(code)`` — trade the OAuth code for tokens + account info.
- ``publish(account, video_path, caption, options)`` — upload & publish.
- ``refresh(account)`` — refresh an expired access token (None if unsupported).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class PublishResult:
    ok: bool
    external_id: str | None = None
    external_url: str | None = None
    error: str | None = None


@dataclass
class PlatformInfo:
    id: str
    name: str
    description: str
    needs_public_url: bool = False  # platform pulls the file from a URL instead of upload
    setup_hint: str = ""


@dataclass
class PublishAccount:
    platform: str
    account_id: str | None = None
    account_name: str | None = None
    access_token: str = ""
    refresh_token: str | None = None
    expires_at: str | None = None
    scopes: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def expired(self, skew: timedelta = timedelta(minutes=5)) -> bool:
        if not self.expires_at:
            return False
        try:
            exp = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return datetime.now(timezone.utc) >= exp - skew


@dataclass
class PublishOptions:
    caption: str = ""
    title: str = ""  # YouTube title (falls back to first caption line)
    youtube_privacy: str = "unlisted"  # public | unlisted | private
    tiktok_privacy: str = "PUBLIC_TO_EVERYONE"  # PUBLIC_TO_EVERYONE | SELF_ONLY | ...
    public_url: str | None = None  # for platforms that need a public file URL


class Publisher(ABC):
    platform_id: str
    info: PlatformInfo

    @abstractmethod
    async def connect_url(self, state: str) -> str:
        """OAuth authorize URL for the user to open."""

    @abstractmethod
    async def exchange_code(self, code: str) -> PublishAccount:
        """Exchange an OAuth code for tokens; raises RuntimeError on failure."""

    async def refresh(self, account: PublishAccount) -> PublishAccount | None:
        """Refresh an expired token. Returns updated account or None if unsupported."""
        return None

    @abstractmethod
    async def publish(
        self,
        account: PublishAccount,
        video_path: Path,
        options: PublishOptions,
    ) -> PublishResult:
        """Upload the video file and publish it. Returns PublishResult."""
