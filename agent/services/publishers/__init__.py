"""Publisher registry."""
from .facebook import FacebookPublisher
from .instagram import InstagramPublisher
from .tiktok import TikTokPublisher
from .youtube import YouTubePublisher

PUBLISHERS = {
    "youtube": YouTubePublisher(),
    "facebook": FacebookPublisher(),
    "instagram": InstagramPublisher(),
    "tiktok": TikTokPublisher(),
}

__all__ = ["PUBLISHERS"]
